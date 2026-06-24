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


def test_cheap_and_accurate_presets_route_correctly():
    # Architect review (2026-06-16): both presets are ONE efficient build —
    # DeepSeek V4 Pro on init/verify/synth (grounded stages). They differ in
    # exactly one cell — the once-firing, ungrounded final gate (cheap = Qwen 3.7
    # Max, accurate = Opus) — plus more verify passes on accurate.
    # VOLUME (2026-06-16): Groq Dev tier is externally gated, so the presets'
    # volume tier routes to DeepSeek V4 Flash (extraction) + Pro (per-cycle gate);
    # `--volume groq` restores gpt-oss-120b when it opens.
    from src.settings import load_settings

    cheap = load_settings(overrides={"cheap": True})
    accurate = load_settings(overrides={"accurate": True})

    # Shared efficient build: identical on every stage EXCEPT the gate.
    for s in (cheap, accurate):
        assert s.roles["reader_subagent"].endpoint == "deepseek_flash"  # volume → DeepSeek (Groq gated)
        assert s.roles["reader_subagent"].model == "deepseek-v4-flash"
        assert s.roles["evaluator"].model == "deepseek-v4-pro"          # per-cycle gate → Pro (judgment)
        assert s.roles["initializer"].model == "deepseek-v4-pro"        # planning → DeepSeek
        assert s.roles["verifier"].model == "deepseek-v4-pro"           # verify is GROUNDED → DeepSeek
        assert s.roles["synthesizer"].model == "deepseek-v4-pro"        # synth → DeepSeek

    # --volume groq restores the designed gpt-oss-120b volume tier when it opens.
    g = load_settings(overrides={"cheap": True, "volume": "groq"})
    assert g.roles["reader_subagent"].endpoint == "groq"
    assert g.roles["reader_subagent"].model == "gpt-oss-120b"

    # The one differing cell: the ungrounded "is this conclusive?" gate.
    assert cheap.roles["final_evaluator"].model == "qwen-3.7-max"        # cheap arm → Qwen
    assert cheap.roles["final_evaluator"].endpoint == "qwen"
    assert accurate.roles["final_evaluator"].model == "claude-opus-4-8"  # accurate arm → Opus
    assert accurate.roles["final_evaluator"].endpoint == "anthropic"

    # Accuracy lever = more (cheap, grounded) DeepSeek verify passes, not a pricier model.
    assert cheap.verification.max_findings == 3
    assert accurate.verification.max_findings == 10

    assert cheap.max_budget_usd == 2.0
    assert accurate.max_budget_usd == 3.0

    # explicit --max-budget-usd still wins over any preset
    assert load_settings(overrides={"cheap": True, "max_budget_usd": 0.5}).max_budget_usd == 0.5


def test_gate_and_verify_depth_override_presets_independently():
    # Architect review (2026-06-16): gate-trust and verify-depth are ORTHOGONAL,
    # so --gate / --verify-depth override their preset cell independently and win
    # over it — the full matrix, not just the two named presets. This is what lets
    # the gate A/B (Opus vs Qwen) ride on the same build.
    import pytest

    from src.errors import ConfigError
    from src.settings import load_settings

    # --cheap --gate opus: cheap build, but a trusted (Opus) terminal gate.
    s = load_settings(overrides={"cheap": True, "gate": "opus"})
    assert s.roles["final_evaluator"].model == "claude-opus-4-8"
    assert s.roles["final_evaluator"].endpoint == "anthropic"
    assert s.roles["verifier"].model == "deepseek-v4-pro"   # rest of cheap build intact
    assert s.verification.max_findings == 3                 # cheap depth unchanged

    # --accurate --gate qwen: deep verify (10 passes) but the cheap Qwen gate.
    s = load_settings(overrides={"accurate": True, "gate": "qwen"})
    assert s.roles["final_evaluator"].model == "qwen-3.7-max"
    assert s.verification.max_findings == 10                # accurate depth unchanged

    # --cheap --verify-depth 10: cheap gate, but deep grounded refutation.
    s = load_settings(overrides={"cheap": True, "verify_depth": 10})
    assert s.roles["final_evaluator"].model == "qwen-3.7-max"  # cheap gate unchanged
    assert s.verification.max_findings == 10                   # depth overridden

    # --gate qwen alone (no preset): overrides the base gate (Opus) without a posture.
    assert load_settings(overrides={"gate": "qwen"}).roles["final_evaluator"].model == "qwen-3.7-max"

    # None overrides are inert — base config gate + depth stand unchanged.
    base = load_settings()
    s = load_settings(overrides={"gate": None, "verify_depth": None})
    assert s.roles["final_evaluator"].model == base.roles["final_evaluator"].model
    assert s.verification.max_findings == base.verification.max_findings

    # an unknown gate is a loud ConfigError, never a silent fallback
    with pytest.raises(ConfigError):
        load_settings(overrides={"gate": "bogus"})


def test_volume_override_swaps_backend_independently():
    # Provider-outage knob (Groq Dev gated 2026-06-16): --volume swaps the 4 volume
    # roles to a fallback backend WITHOUT touching judgment/gate routing — same
    # independent-knob pattern as --gate.
    import pytest

    from src.errors import ConfigError
    from src.settings import load_settings

    # default: --cheap routes volume to DeepSeek (Groq Dev tier gated 2026-06-16);
    # --volume groq restores the designed gpt-oss-120b tier when it opens.
    assert load_settings(overrides={"cheap": True}).roles["reader_subagent"].endpoint == "deepseek_flash"
    assert load_settings(overrides={"cheap": True, "volume": "groq"}).roles["reader_subagent"].endpoint == "groq"

    # --volume deepseek: extraction roles -> V4 Flash; the multi-turn per-cycle
    # evaluator (judgment) -> V4 Pro (Flash exhausts its turn budget); gate + synth
    # untouched.
    ds = load_settings(overrides={"cheap": True, "volume": "deepseek"})
    for role in ("worker", "reader_subagent", "compose"):
        assert ds.roles[role].endpoint == "deepseek_flash", role
        assert ds.roles[role].model == "deepseek-v4-flash", role
    assert ds.roles["evaluator"].endpoint == "deepseek"          # per-cycle gate -> Pro (reliable)
    assert ds.roles["evaluator"].model == "deepseek-v4-pro"
    assert ds.roles["final_evaluator"].model == "qwen-3.7-max"   # gate unchanged
    assert ds.roles["synthesizer"].model == "deepseek-v4-pro"    # judgment unchanged

    # --volume local: $0 Ollama; accurate gate still Opus
    loc = load_settings(overrides={"accurate": True, "volume": "local"})
    assert loc.roles["reader_subagent"].endpoint == "local"
    assert loc.roles["reader_subagent"].model == "gpt-oss-20b-32k"
    assert loc.roles["final_evaluator"].model == "claude-opus-4-8"

    # composes with --gate (orthogonal knobs both override their cells)
    combo = load_settings(overrides={"cheap": True, "volume": "deepseek", "gate": "opus"})
    assert combo.roles["worker"].endpoint == "deepseek_flash"
    assert combo.roles["final_evaluator"].model == "claude-opus-4-8"

    # unknown volume -> loud ConfigError
    with pytest.raises(ConfigError):
        load_settings(overrides={"volume": "bogus"})


def test_search_preflight_prefers_searxng_then_ddg_then_aborts(monkeypatch):
    # Robustness (2026-06-24): pipeline search is SearXNG-primary with a Docker-free
    # DuckDuckGo fallback. Preflight returns the live backend, and aborts ONLY if
    # both are down — so a SearXNG/Docker outage degrades gracefully (the exact
    # failure that produced an empty 0-finding report) instead of killing the run.
    import pytest

    import src.tools.search as search_mod
    from src.errors import ConfigError
    from src.settings import load_settings

    s = load_settings(overrides={"cheap": True})
    dead = s.model_copy(
        update={"search": s.search.model_copy(update={"searxng_base_url": "http://127.0.0.1:59321"})}
    )

    async def _ddg_ok(query, max_results, timeout=10.0):
        return [{"title": "t", "url": "u", "snippet": "s"}]

    # SearXNG dead + DDG works -> graceful fallback to "ddg", no abort.
    monkeypatch.setattr(search_mod, "ddg_results", _ddg_ok)
    assert search_mod.preflight_search(dead, timeout=2.0) == "ddg"

    # No SearXNG configured at all + DDG works -> "ddg".
    none_cfg = s.model_copy(
        update={"search": s.search.model_copy(update={"searxng_base_url": None})}
    )
    assert search_mod.preflight_search(none_cfg, timeout=2.0) == "ddg"

    # SearXNG dead AND DDG dead -> abort: no search backend at all.
    async def _ddg_fail(query, max_results, timeout=10.0):
        from src.tools import ConnectorError

        raise ConnectorError("no network")

    monkeypatch.setattr(search_mod, "ddg_results", _ddg_fail)
    with pytest.raises(ConfigError, match="no search backend"):
        search_mod.preflight_search(dead, timeout=2.0)


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
