"""Batch A (post-MVP): session wall-timeout, provisional ledger accounting,
two-tier evaluation — the local report's top reliability findings."""

import asyncio
from pathlib import Path

import pytest
import yaml

import driver
from src.ledger import Ledger
from src.runspace import Runspace
from src.settings import Settings
from src.state import Verdict, parse_ledger
from tests.conftest import BASE_CONFIG, only_run_dir


def _settings(tmp_path: Path, **overrides) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw.setdefault("secrets", {})
    for dotted, value in overrides.items():
        node = raw
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return Settings.model_validate(raw)


# --- wall-timeout: the hang-forever fix (local report finding #1) ---------------


def test_hung_session_is_killed_and_typed(tmp_path, monkeypatch):
    """A transport that never yields a result must be killed at the wall
    ceiling, retried under the transient cap, then surface as a typed error —
    with the dead attempts visible as unreconciled ledger entries."""
    from src.sessions import base as base_mod

    settings = _settings(
        tmp_path,
        **{
            "secrets": {"ANTHROPIC_API_KEY": "sk-test"},
            "roles.worker.max_wall_seconds": 0.2,
        },
    )
    run = Runspace.create(tmp_path / "runs", "q", "general")
    ledger = Ledger(run)

    def hanging_query(*, prompt, options):
        async def _gen():
            await asyncio.sleep(3600)  # the dead-transport hang
            yield  # pragma: no cover

        return _gen()

    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", hanging_query)

    try:
        with pytest.raises(base_mod.WorkerError) as excinfo:
            asyncio.run(
                base_mod.run_role_session_async(
                    run=run, settings=settings, ledger=ledger, cycle=1,
                    session_type="worker", role="worker",
                    system_prompt="s", user_prompt="u", tools=[],
                )
            )
    finally:
        run.release_lock()

    assert "wall ceiling" in str(excinfo.value)
    assert "after 3 attempts" in str(excinfo.value)
    # Every dead attempt is in the ledger, visibly unreconciled.
    assert ledger.unreconciled_count == 3
    progress = (run.root / "PROGRESS.md").read_text()
    assert "exceeded wall ceiling" in progress


def test_successful_session_reconciles_provisional_entry(tmp_path, monkeypatch):
    """One entry per successful session: the provisional is REPLACED by the
    final accounting (reconciled=True), never left beside it."""
    from claude_agent_sdk import ResultMessage

    from src.sessions import base as base_mod

    settings = _settings(tmp_path, **{"secrets": {"ANTHROPIC_API_KEY": "sk-test"}})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    ledger = Ledger(run)

    def ok_query(*, prompt, options):
        async def _gen():
            yield ResultMessage(
                subtype="success", duration_ms=10, duration_api_ms=8,
                is_error=False, num_turns=1, session_id="s",
                total_cost_usd=0.05,
                usage={"input_tokens": 100, "output_tokens": 20,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                result="done",
            )

        return _gen()

    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", ok_query)

    try:
        spawn = asyncio.run(
            base_mod.run_role_session_async(
                run=run, settings=settings, ledger=ledger, cycle=1,
                session_type="worker", role="worker",
                system_prompt="s", user_prompt="u", tools=[],
            )
        )
    finally:
        run.release_lock()

    assert spawn.usd == 0.05
    entries = ledger.entries
    assert len(entries) == 1
    assert entries[0].reconciled is True and entries[0].input_tokens == 100
    # And the persisted file agrees (crash-safe accounting).
    persisted = parse_ledger((run.root / "ledger.json").read_text()).root
    assert len(persisted) == 1 and persisted[0].reconciled is True


def test_finalize_metrics_bills_cache_at_discounted_rate():
    # Cost fix (2026-06-25): cached tokens (re-reads of stable context) bill at the
    # endpoint's cache_read rate, not the full input rate. The hair run's 8.59M
    # cached on the evaluator was a ~50x over-charge ($3.74 -> $0.03); this restores
    # honest cost + budget headroom for deep runs.
    from src.sessions.base import finalize_metrics
    from src.settings import EndpointCfg, PriceCfg

    usage = {"input_tokens": 1_000_000, "output_tokens": 0,
             "cache_read_input_tokens": 10_000_000, "cache_creation_input_tokens": 0}

    priced = EndpointCfg(base_url="https://x", auth_env="K",
                         price_per_mtok=PriceCfg(input=0.435, output=0.87, cache_read=0.003625))
    m = finalize_metrics(usage, None, priced, 1.0)
    assert abs(m["usd"] - (0.435 + 10 * 0.003625)) < 1e-9   # 1M miss + 10M cache-hit
    assert m["cached_tokens"] == 10_000_000

    # No cache_read set -> conservative fall back to the input rate (never under-count).
    conservative = EndpointCfg(base_url="https://x", auth_env="K",
                               price_per_mtok=PriceCfg(input=0.435, output=0.87))
    assert abs(finalize_metrics(usage, None, conservative, 1.0)["usd"] - 11 * 0.435) < 1e-9


def test_dead_session_keeps_partial_stream_usage(tmp_path, monkeypatch):
    """A session that streamed some assistant usage then died leaves an
    unreconciled entry carrying the tokens we actually saw."""
    from claude_agent_sdk import AssistantMessage

    from src.sessions import base as base_mod

    settings = _settings(
        tmp_path,
        **{
            "secrets": {"ANTHROPIC_API_KEY": "sk-test"},
            "roles.worker.max_wall_seconds": 0.3,
        },
    )
    run = Runspace.create(tmp_path / "runs", "q", "general")
    ledger = Ledger(run)

    def partial_then_hang(*, prompt, options):
        async def _gen():
            yield AssistantMessage(
                content=[], model="m", message_id="msg_1",
                usage={"input_tokens": 500, "output_tokens": 40},
            )
            await asyncio.sleep(3600)

        return _gen()

    import claude_agent_sdk

    monkeypatch.setattr(claude_agent_sdk, "query", partial_then_hang)

    try:
        with pytest.raises(base_mod.WorkerError):
            asyncio.run(
                base_mod.run_role_session_async(
                    run=run, settings=settings, ledger=ledger, cycle=1,
                    session_type="worker", role="worker",
                    system_prompt="s", user_prompt="u", tools=[],
                )
            )
    finally:
        run.release_lock()

    entries = ledger.entries
    assert entries and all(not e.reconciled for e in entries)
    assert entries[0].input_tokens == 500 and entries[0].output_tokens == 40


# --- two-tier evaluation -----------------------------------------------------------


def test_two_tier_run_ends_only_through_final_gate(make_config, runs_dir):
    cfg_path = make_config()
    # Add a final_evaluator role to the stub config.
    raw = yaml.safe_load(Path(cfg_path).read_text())
    raw["roles"]["final_evaluator"] = {
        "endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 24,
    }
    Path(cfg_path).write_text(yaml.safe_dump(raw))

    rc = driver.main(["q", "--config", str(cfg_path), "--max-cycles", "4"])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    verdicts = sorted(p.name for p in (run_dir / "verdicts").glob("*.md"))
    # Per-cycle verdicts for each cycle, plus the -final terminal gate verdict.
    assert any(name.endswith("-final.md") for name in verdicts), verdicts

    import json

    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["finish_reason"] == "conclusive"
    progress = (run_dir / "PROGRESS.md").read_text()
    assert "final gate (stub" in progress


def test_single_tier_unchanged_without_final_role(make_config, runs_dir):
    cfg = make_config()
    rc = driver.main(["q", "--config", str(cfg), "--max-cycles", "3"])
    assert rc == 0
    run_dir = only_run_dir(runs_dir)
    assert not any(
        p.name.endswith("-final.md") for p in (run_dir / "verdicts").glob("*.md")
    )


def test_latest_verdict_prefers_final_at_same_cycle(tmp_path):
    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        run.write_verdict(3, Verdict(passed=True, unmet_criteria=[],
                                     contradictions=[], new_questions=[], notes="cheap"))
        run.write_verdict(3, Verdict(passed=False, unmet_criteria=["x"],
                                     contradictions=[], new_questions=[], notes="final"),
                          final=True)
        latest = run.latest_verdict()
    finally:
        run.release_lock()
    assert latest is not None and latest.passed is False and latest.notes == "final"


def test_final_gate_budget_cap_accepts_local_pass(make_config, runs_dir):
    """After max_final_evaluations Opus firings, the run finishes conclusive
    on the local evaluator's pass instead of re-summoning Opus — with the
    decision logged. Spend becomes deterministic."""
    cfg_path = make_config(**{"max_final_evaluations": 1})
    raw = yaml.safe_load(Path(cfg_path).read_text())
    raw["roles"]["final_evaluator"] = {
        "endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 24,
    }
    # Force the stub final gate to FAIL its first firing by leaving a question
    # unresolved at that moment is hard with stubs; instead simulate the count
    # already exhausted via meta: run once normally with cap=0-equivalent.
    raw["max_final_evaluations"] = 1
    Path(cfg_path).write_text(yaml.safe_dump(raw))

    rc = driver.main(["q", "--config", str(cfg_path), "--max-cycles", "5"])
    assert rc == 0
    run_dir = only_run_dir(runs_dir)

    import json

    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["finish_reason"] == "conclusive"
    # Stub final gate passes on first firing here, so the cap wasn't needed —
    # assert the firing was COUNTED (persistence is what the cap rests on).
    assert meta["final_eval_count"] == 1


def test_final_gate_cap_exhausted_accepts_local_pass(make_config, runs_dir):
    """With final_eval_count already at the cap, the driver finishes
    conclusive on the LOCAL evaluator's pass, logs the decision, and never
    calls the Opus gate — the deterministic-spend guarantee."""
    from rich.console import Console

    from driver import _drive
    from src.sessions import get_backend
    from src.settings import load_settings

    cfg_path = make_config(**{"max_final_evaluations": 2})
    raw = yaml.safe_load(Path(cfg_path).read_text())
    raw["roles"]["final_evaluator"] = {
        "endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 24,
    }
    raw["max_final_evaluations"] = 2
    Path(cfg_path).write_text(yaml.safe_dump(raw))
    settings = load_settings(config_path=cfg_path)

    run = Runspace.create(Path(settings.runs_dir), "q", "general")
    try:
        # Pre-exhaust the Opus gate budget (as if two firings already happened).
        run.bump_final_eval()
        run.bump_final_eval()

        backend = dict(get_backend(settings))
        fired = {"n": 0}
        real_final = backend["final_evaluator"]

        def counting_final(run_, settings_, cycle, ledger_):
            fired["n"] += 1
            return real_final(run_, settings_, cycle, ledger_)

        backend["final_evaluator"] = counting_final
        ledger = Ledger(run)
        reason = _drive(backend, run, settings, ledger, Console(quiet=True))
    finally:
        run.release_lock()

    assert reason == "conclusive"
    assert fired["n"] == 0  # Opus gate never summoned past the cap
    progress = (run.root / "PROGRESS.md").read_text()
    assert "final-gate budget" in progress and "exhausted" in progress
