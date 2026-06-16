"""Root-cause fix (2026-06-15): the per-cycle evaluator ran on the local 32k
model but received full findings + the full source registry, hitting ~30.7k
tokens at 13 findings and 5xx-ing the local endpoint. The cheap gate must be
context-bounded so deep/comprehensive runs complete; the Opus final gate keeps
full text. These tests pin the bounds."""

from pathlib import Path

from src.runspace import Runspace
from src.sessions import common
from src.state import FindingMeta, OpenQuestion, QuestionList, SourceRecord, SourceRegistry, utcnow


def _run_with_findings(tmp_path: Path, n: int, body_chars: int) -> Runspace:
    run = Runspace.create(tmp_path / "runs", "q", "general")
    qs = []
    for i in range(n):
        qid = f"q-{i+1:03d}"
        qs.append(OpenQuestion(id=qid, question=f"facet {i}", priority=3, created_by="initializer"))
        run.write_finding(
            f"{qid}-c01",
            FindingMeta(question_id=qid, source_ids=["src-x"], confidence=0.8),
            f"Finding {i}. " + ("lorem ipsum dolor sit amet. " * (body_chars // 28)),
        )
    run.save_questions(QuestionList(qs))
    return run


def test_findings_digest_total_char_budget_bounds_output(tmp_path):
    # 20 findings x ~6000 chars = ~120k chars unbounded. With a 40k budget the
    # result must stay near budget (the exact failure mode at scale).
    run = _run_with_findings(tmp_path, n=20, body_chars=6000)
    unbounded = common.findings_digest(run, full_bodies=True)
    bounded = common.findings_digest(run, full_bodies=True, max_total_chars=40000)
    assert len(unbounded) > 100_000           # confirms the unbounded blowup
    assert len(bounded) <= 55_000             # budget + header overhead
    # every finding still represented (header present) even when truncated
    for i in range(20):
        assert f"q-{i+1:03d}" in bounded
    assert "truncated" in bounded.lower()
    run.release_lock()


def test_findings_digest_none_budget_is_full(tmp_path):
    run = _run_with_findings(tmp_path, n=3, body_chars=2000)
    full = common.findings_digest(run, full_bodies=True)
    none_budget = common.findings_digest(run, full_bodies=True, max_total_chars=None)
    assert full == none_budget                # default unchanged (byte-identical)
    run.release_lock()


def test_budget_flag_swaps_judgment_roles_to_cheap():
    # --budget keeps a comprehensive run under ~$1 by swapping Opus judgment
    # roles to cheaper backends + capping verification.
    from src.settings import load_settings

    norm = load_settings()
    bud = load_settings(overrides={"budget": True})
    # normal posture: compose Haiku, synthesis + verifier on Opus
    assert norm.roles["compose"].endpoint == "anthropic"
    assert "opus" in norm.roles["synthesizer"].model
    # budget posture: compose local ($0), synthesis + verifier on Haiku, capped
    assert bud.roles["compose"].endpoint == "local"
    assert "haiku" in bud.roles["synthesizer"].model
    assert "haiku" in bud.roles["verifier"].model
    assert bud.verification.max_findings == 3
    assert not hasattr(bud, "budget")  # meta-config never leaks into Settings


def test_cheap_preset_caps_budget_under_one_dollar_but_explicit_wins():
    # --cheap (Config A, all-DeepSeek) makes the operator's firm "under $1"
    # rule STRUCTURAL: the preset promotes a $1 hard breaker so a runaway
    # marathon run finishes-partial at $1 rather than overspending. An explicit
    # --max-budget-usd still wins (presets never override explicit CLI flags).
    from src.settings import load_settings

    cheap = load_settings(overrides={"cheap": True})
    assert cheap.max_budget_usd == 1.0
    explicit = load_settings(overrides={"cheap": True, "max_budget_usd": 3.0})
    assert explicit.max_budget_usd == 3.0
    # the cap is preset-scoped: a normal run keeps the config default (not 1.0)
    assert load_settings().max_budget_usd != 1.0


def test_evaluator_per_cycle_prompt_is_bounded_final_is_full(tmp_path):
    # The wiring: the per-cycle gate (final=False, local 32k model) excerpts
    # findings; the Opus final gate (final=True) gets full text.
    import yaml
    from src.ledger import Ledger
    from src.profiles import get_profile
    from src.sessions import evaluator
    from src.settings import Settings
    from tests.conftest import BASE_CONFIG

    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["secrets"] = {"ANTHROPIC_API_KEY": "sk-test", "OLLAMA_AUTH": "ollama"}
    raw["evaluator"] = {"per_cycle_findings_chars": 8000, "per_cycle_max_sources": 10}
    settings = Settings.model_validate(raw)

    run = _run_with_findings(tmp_path, n=15, body_chars=6000)  # ~90k chars of bodies
    run.write_text("PLAN.md", "# plan\n")
    ledger = Ledger(run)
    profile = get_profile("general")

    per_cycle = evaluator._build_user_prompt(run, settings, ledger, 5, final=False)
    final = evaluator._build_user_prompt(run, settings, ledger, 5, final=True)
    assert len(per_cycle) < len(final)              # bounded < full
    assert "truncated" in per_cycle and "truncated" not in final
    assert len(per_cycle) < 30000                   # well under what 5xx-ed
    run.release_lock()


def test_sources_digest_caps_to_most_credible(tmp_path):
    reg = SourceRegistry(root={
        f"src-{i:03d}": SourceRecord(
            url=f"https://e/{i}", title=f"t{i}", kind="web",
            credibility=i, retrieved_at=utcnow(), notes="",
        ) for i in range(100)
    })
    full = common.sources_digest(reg)
    capped = common.sources_digest(reg, max_sources=20)
    assert full.count("\n") >= 99
    assert capped.count("src-") <= 21         # 20 + maybe a "+N more" line
    assert "src-099" in capped                # highest credibility kept
    assert "src-000" not in capped            # lowest dropped
    assert "more" in capped.lower()           # truncation disclosed
