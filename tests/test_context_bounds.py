"""Root-cause fix (2026-06-15): the per-cycle evaluator ran on the local 32k
model but received full findings + the full source registry, hitting ~30.7k
tokens at 13 findings and 5xx-ing the local endpoint. The cheap gate must be
context-bounded so deep/comprehensive runs complete; the Opus final gate keeps
full text. These tests pin the bounds."""

from pathlib import Path

import pytest

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
    assert "elided" in bounded.lower()   # head+tail elision marker (audit #4)
    run.release_lock()


def test_findings_digest_preserves_tail_not_just_head(tmp_path):
    # audit #4: findings_digest used to head-only-slice, dropping a finding's
    # tail — so a late claim/citation became invisible to the default-FAIL
    # evaluator, which then judged on content it never saw. The fix keeps head
    # AND tail (mirrors reader.py). A sentinel at the very end must survive a
    # tight budget that forces truncation.
    run = Runspace.create(tmp_path / "runs", "q", "general")
    qid = "q-001"
    run.save_questions(QuestionList(
        [OpenQuestion(id=qid, question="facet", priority=3, created_by="initializer")]
    ))
    body = (
        "HEAD_SENTINEL begins this finding. "
        + ("filler middle content. " * 4000)          # ~92k chars of middle
        + " The conclusion cites TAIL_SENTINEL [src-x]."
    )
    run.write_finding(
        f"{qid}-c01",
        FindingMeta(question_id=qid, source_ids=["src-x"], confidence=0.8),
        body,
    )
    digest = common.findings_digest(run, full_bodies=True, max_total_chars=4000)
    assert len(digest) < len(body)             # truncation actually happened
    assert "HEAD_SENTINEL" in digest           # head kept (old code kept this too)
    assert "TAIL_SENTINEL" in digest           # tail kept (old head-only code DROPPED this)
    assert "elided" in digest.lower()          # the gap is marked, not silent
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
    assert cheap.roles["final_evaluator"].model == "claude-sonnet-4-6"   # cheap arm → Sonnet (reliable gate, Opus review #5)
    assert cheap.roles["final_evaluator"].endpoint == "anthropic"
    assert accurate.roles["final_evaluator"].model == "claude-opus-4-8"  # accurate arm → Opus
    assert accurate.roles["final_evaluator"].endpoint == "anthropic"

    # Accuracy lever = more (cheap, grounded) DeepSeek verify passes, not a pricier model.
    assert cheap.verification.max_findings == 6   # raised 3->6 (Opus review: verify wider)
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
    assert s.verification.max_findings == 6                 # cheap depth unchanged (3->6)

    # --accurate --gate qwen: deep verify (10 passes) but the cheap Qwen gate.
    s = load_settings(overrides={"accurate": True, "gate": "qwen"})
    assert s.roles["final_evaluator"].model == "qwen-3.7-max"
    assert s.verification.max_findings == 10                # accurate depth unchanged

    # --cheap --verify-depth 10: cheap gate, but deep grounded refutation.
    s = load_settings(overrides={"cheap": True, "verify_depth": 10})
    assert s.roles["final_evaluator"].model == "claude-sonnet-4-6"  # cheap gate unchanged (now Sonnet)
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
    assert ds.roles["final_evaluator"].model == "claude-sonnet-4-6"   # gate unchanged (now Sonnet)
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


def test_exhaustive_promotes_read_dials_beyond_comprehensive():
    # --exhaustive (Opus review depth dials): comprehensive's deep bundle PLUS the
    # read budget, so a vast topic ingests 1000+ pages. Merged 2026-06-30 (audit
    # #15): absorbed the near-identical test_exhaustive_promotes_read_budget_and_
    # deep_bounds — its cheap-combo + max_cycles/max_depth assertions live here now
    # so the exhaustive dials have ONE regression home. Explicit CLI flags still win.
    from src.settings import load_settings

    s = load_settings(overrides={"exhaustive": True})
    assert s.worker_pipeline.max_reads == 45          # the read dial (vs 12 default)
    assert s.worker_pipeline.per_domain_cap == 5      # vs 3
    assert s.max_cycles == 200
    assert s.question_tree.seed_target == 20           # deeper tree than comprehensive's 12
    assert s.question_tree.max_questions == 200
    assert s.question_tree.max_depth == 8
    assert s.verification.enabled and s.waves.enabled  # verify + waves on, like comprehensive
    # composing with a cost preset still promotes the read dials — the depth bundle
    # is orthogonal to the cheap/accurate routing build (was a separate test).
    combo = load_settings(overrides={"cheap": True, "exhaustive": True})
    assert combo.worker_pipeline.max_reads == 45 and combo.worker_pipeline.per_domain_cap == 5
    # an explicit --max-budget-usd still wins over the bundle
    assert load_settings(overrides={"exhaustive": True, "max_budget_usd": 3.0}).max_budget_usd == 3.0


def test_comprehensive_with_cost_preset_keeps_depth_bundle():
    # audit #9: --comprehensive promotes max_cycles/max_wall_hours/max_budget_usd as
    # one bundle (150 / 8.0 / 25.0); a cost preset applied AFTER overwrites only the
    # scalars it names. --cheap names only max_budget_usd (2.0), so the composition
    # is INTENDED to be "comprehensive ambition, cheap ceiling" — the tight $2 budget
    # breaker is the binding constraint and trips long before 150 cycles / 8h. This
    # pins that behavior so a future preset edit can't silently change it.
    from src.settings import load_settings

    s = load_settings(overrides={"comprehensive": True, "cheap": True})
    assert s.max_budget_usd == 2.0      # cheap's ceiling wins (the binding constraint)
    assert s.max_cycles == 150          # comprehensive's cycle bundle survives
    assert s.max_wall_hours == 8.0      # comprehensive's wall bundle survives
    # --accurate names max_budget_usd 3.0; same composition shape.
    a = load_settings(overrides={"comprehensive": True, "accurate": True})
    assert a.max_budget_usd == 3.0 and a.max_cycles == 150 and a.max_wall_hours == 8.0


@pytest.mark.real_preflight  # this test IS the preflight; opt out of the autouse stub
def test_search_preflight_prefers_serper_then_searxng_then_ddg_then_aborts(monkeypatch):
    # Preference order (2026-06-25): Serper (portable Google API) -> SearXNG
    # (self-host) -> DuckDuckGo (free fallback). Preflight returns the live backend
    # and aborts ONLY if NONE answers — so an outage degrades gracefully (the exact
    # failure that produced an empty 0-finding report) instead of killing the run.
    import pytest
    from pydantic import SecretStr

    import src.tools.search as search_mod
    from src.errors import ConfigError
    from src.settings import load_settings

    s = load_settings(overrides={"cheap": True})

    # (1) Serper key present + reachable -> "serper". Inject the key (so the test
    # doesn't depend on .env) and mock the probe (so it never spends a credit).
    class _OK:
        def raise_for_status(self):
            return None

        def json(self):
            return {"organic": []}

    with_serper = s.model_copy(
        update={
            "search": s.search.model_copy(update={"serper_api_key_env": "SERPER_API_KEY"}),
            "secrets": {**s.secrets, "SERPER_API_KEY": SecretStr("test-key")},
        }
    )
    monkeypatch.setattr(search_mod.httpx, "post", lambda *a, **k: _OK())
    assert search_mod.preflight_search(with_serper, timeout=2.0) == "serper"

    # The remaining chain is the NO-serper fallback — strip the key so Serper is
    # skipped and SearXNG/DDG are exercised as before.
    s = s.model_copy(
        update={"search": s.search.model_copy(update={"serper_api_key_env": None})}
    )
    dead = s.model_copy(
        update={"search": s.search.model_copy(update={"searxng_base_url": "http://127.0.0.1:59321"})}
    )

    class _SearXNGFail:
        """Mock httpx.get response for a failed SearXNG probe. Raises the real
        transport-error type (httpx.HTTPError subclass): the probe's except is
        deliberately narrow now, so a bare Exception would — correctly — escape
        as a coding error instead of reading as "backend unreachable"."""
        def raise_for_status(self):
            raise search_mod.httpx.ConnectError("Connection refused")

    async def _ddg_ok(query, max_results, timeout=10.0):
        return [{"title": "t", "url": "u", "snippet": "s"}]

    # SearXNG dead + DDG works -> graceful fallback to "ddg", no abort.
    monkeypatch.setattr(search_mod.httpx, "get", lambda *a, **k: _SearXNGFail())
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
    # per-cycle carries the head+tail elision marker (audit #4); the full Opus
    # final gate has no elision because it gets untruncated bodies.
    assert "elided" in per_cycle and "elided" not in final
    assert len(per_cycle) < 30000                   # well under what 5xx-ed
    run.release_lock()


def test_final_gate_digest_is_bounded_when_oversized(tmp_path):
    # audit #12: the Opus final gate's digest caps (final_findings_chars=150000 /
    # final_max_sources=120) were wired but no test pushed past them — the only
    # final=True test seeds ~90k chars (< 150k default), so it couldn't tell the
    # cap from no-cap; reverting the wiring passed the suite. Override both caps
    # SMALL and seed past them: the final prompt must actually truncate findings
    # AND cap the source list, proving the cost-discipline wiring is live.
    import yaml
    from src.ledger import Ledger
    from src.sessions import evaluator
    from src.settings import Settings
    from src.state import SourceRecord, SourceRegistry
    from tests.conftest import BASE_CONFIG

    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["secrets"] = {"ANTHROPIC_API_KEY": "sk-test", "OLLAMA_AUTH": "ollama"}
    raw["evaluator"] = {
        "per_cycle_findings_chars": 8000, "per_cycle_max_sources": 10,
        "final_findings_chars": 10000, "final_max_sources": 3,  # min allowed / tiny, to force the caps
    }
    settings = Settings.model_validate(raw)

    run = _run_with_findings(tmp_path, n=15, body_chars=6000)  # ~90k chars >> 10000 cap
    run.write_text("PLAN.md", "# plan\n")
    reg = SourceRegistry({})
    for i in range(8):  # 8 sources >> final_max_sources=3
        reg.root[f"src-{i:02d}"] = SourceRecord(
            url=f"https://ex/{i}", title=f"t{i}", kind="web",
            credibility=10 + i, retrieved_at=utcnow(), notes="",
        )
    run.save_sources(reg)
    ledger = Ledger(run)

    final = evaluator._build_user_prompt(run, settings, ledger, 5, final=True)
    assert "elided" in final                    # findings truncated by final_findings_chars
    assert "omitted to fit context" in final    # sources capped by final_max_sources
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


# --- Config validation: dangling refs, required roles, preset typos (audit batch A) ---


def test_dangling_role_endpoint_fails_loudly_at_load(make_config):
    # ultracode audit #9: the cross-check's dangling-reference detection had no
    # test. A role pointing at a nonexistent endpoint must fail at config LOAD.
    import pytest

    from src.errors import ConfigError
    from src.settings import load_settings

    cfg = make_config(**{"roles.worker.endpoint": "nonesuch"})
    with pytest.raises(ConfigError, match="unknown endpoint 'nonesuch'"):
        load_settings(config_path=str(cfg))


def test_dangling_endpoint_fallback_fails_loudly_at_load(make_config):
    # ultracode audit #9: an endpoint whose fallback points at a nonexistent
    # endpoint must also fail at load (the fallback feature's own validator).
    import pytest

    from src.errors import ConfigError
    from src.settings import load_settings

    cfg = make_config(**{"endpoints.anthropic.fallback": {"endpoint": "ghost", "model": "m"}})
    with pytest.raises(ConfigError, match="fallback references unknown endpoint 'ghost'"):
        load_settings(config_path=str(cfg))


def test_missing_core_role_fails_loudly_at_load(make_config):
    # ultracode audit #11: the always-required roles (init/worker/eval/synth) are
    # validated at LOAD, not lazily on the role() lookup mid-run.
    import copy

    import pytest

    from src.errors import ConfigError
    from src.settings import load_settings
    from tests.conftest import BASE_CONFIG

    roles = copy.deepcopy(BASE_CONFIG["roles"])
    del roles["synthesizer"]
    cfg = make_config(**{"roles": roles})
    with pytest.raises(ConfigError, match="always-required role"):
        load_settings(config_path=str(cfg))


def test_preset_typod_role_key_fails_loudly(make_config):
    # ultracode audit #8 (HIGH): a typo'd role key in a preset block used to
    # SILENTLY splice in a dead role while leaving the real role's (often pricier)
    # base routing in place. Now it raises ConfigError at load instead of silently
    # narrowing — the behavior CLAUDE.md §3 invariant 8 demands.
    import pytest

    from src.errors import ConfigError
    from src.settings import load_settings

    cfg = make_config(
        **{"cheap": {"roles": {"intializer": {"endpoint": "anthropic",
                                              "model": "m", "max_turns": 4}}}}
    )
    with pytest.raises(ConfigError, match="unknown role 'intializer'"):
        load_settings(config_path=str(cfg), overrides={"cheap": True})


def test_default_config_needs_only_anthropic_key():
    # Release gate (v1.0): a fresh clone with ONLY an ANTHROPIC_API_KEY must
    # work out of the box. Before this change the base config routed
    # worker/reader_subagent/evaluator to a local Ollama model
    # (gpt-oss-20b-32k) that no new user has — first cycle failed. Every
    # BASE role must resolve to the anthropic endpoint; local/DeepSeek/Groq
    # postures remain opt-in via presets, --volume, or --config.
    from src.settings import load_settings

    s = load_settings()
    endpoints = {name: rc.endpoint for name, rc in s.roles.items()}
    assert set(endpoints.values()) == {"anthropic"}, endpoints
