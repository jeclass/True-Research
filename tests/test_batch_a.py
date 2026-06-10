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
