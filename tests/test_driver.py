"""Driver loop integration: breakers, stall, resume — all through main()."""

from pathlib import Path

import pytest

import driver
from src.errors import StateError
from src.runspace import PLAN_FILE, REPORT_FILE, Runspace
from src.sessions import get_backend
from src.state import parse_ledger, parse_run_meta
from tests.conftest import only_run_dir


def _meta(run_dir: Path):
    return parse_run_meta((run_dir / "run.json").read_text())


def _ledger(run_dir: Path):
    return parse_ledger((run_dir / "ledger.json").read_text()).root


def test_happy_run_reaches_conclusive(make_config, runs_dir):
    cfg = make_config()
    rc = driver.main(["test question", "--profile", "general", "--config", str(cfg),
                      "--max-cycles", "3"])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.status == "finished" and meta.finish_reason == "conclusive"
    assert meta.last_cycle == 3

    entries = _ledger(run_dir)
    by_type = [e.session_type for e in entries]
    assert by_type.count("initializer") == 1
    assert by_type.count("worker") == 3
    assert by_type.count("evaluator") == 3
    assert by_type.count("synthesizer") == 1
    assert all(e.endpoint == "anthropic" for e in entries)

    assert (run_dir / REPORT_FILE).is_file()
    assert "PARTIAL" not in (run_dir / REPORT_FILE).read_text()
    assert sorted(p.name for p in (run_dir / "verdicts").glob("*.md")) == [
        "cycle-1.md", "cycle-2.md", "cycle-3.md",
    ]
    assert len(list((run_dir / "findings").glob("*.md"))) == 3


def test_budget_breaker_trips_at_zero(make_config, runs_dir):
    cfg = make_config()
    rc = driver.main(["q", "--config", str(cfg), "--max-budget-usd", "0"])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.status == "finished" and meta.finish_reason == "budget"

    # Breaker fired before EVERY session — even the initializer never ran.
    assert not (run_dir / PLAN_FILE).exists()
    entries = _ledger(run_dir)
    assert [e.session_type for e in entries] == ["synthesizer"]

    report = (run_dir / REPORT_FILE).read_text()
    assert "PARTIAL" in report and "budget" in report


def test_max_cycles_breaker(make_config, runs_dir):
    cfg = make_config(**{"stub.seed_questions": 5})
    rc = driver.main(["q", "--config", str(cfg), "--max-cycles", "2"])
    assert rc == 0
    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.finish_reason == "max_cycles"
    assert meta.last_cycle == 2
    assert "PARTIAL" in (run_dir / REPORT_FILE).read_text()


def test_forced_stall_halts_after_threshold(make_config, runs_dir):
    cfg = make_config(**{"stub.worker_no_delta": True})
    rc = driver.main(["q", "--config", str(cfg)])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.finish_reason == "stall"
    assert meta.last_cycle == 2  # stall_cycles = 2 consecutive no-delta cycles

    progress = (run_dir / "PROGRESS.md").read_text()
    assert "STALL" in progress and "halting per invariant 5" in progress


def test_resume_reconstructs_from_disk(make_config, runs_dir, monkeypatch):
    cfg = make_config()

    real_backend = get_backend  # capture before patching

    def crashing_backend(settings):
        backend = dict(real_backend(settings))
        real_evaluator = backend["evaluator"]

        def evaluator(run, settings_, cycle, ledger_):
            if cycle == 2:
                raise RuntimeError("simulated kill mid-cycle")
            return real_evaluator(run, settings_, cycle, ledger_)

        backend["evaluator"] = evaluator
        return backend

    monkeypatch.setattr(driver, "get_backend", crashing_backend)
    with pytest.raises(RuntimeError, match="simulated kill"):
        driver.main(["q", "--config", str(cfg), "--max-cycles", "5"])
    monkeypatch.undo()

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.status == "running" and meta.last_cycle == 1  # cycle 2 not completed

    rc = driver.main(["--resume", run_dir.name, "--config", str(cfg), "--max-cycles", "5"])
    assert rc == 0

    meta = _meta(run_dir)
    assert meta.status == "finished" and meta.finish_reason == "conclusive"
    # No duplicated work: 3 questions -> exactly 3 findings, cycles continuous.
    assert len(list((run_dir / "findings").glob("*.md"))) == 3
    assert (run_dir / "verdicts" / f"cycle-{meta.last_cycle}.md").is_file()


def test_resume_of_finished_run_errors_cleanly(make_config, runs_dir):
    cfg = make_config()
    assert driver.main(["q", "--config", str(cfg), "--max-cycles", "3"]) == 0
    run_dir = only_run_dir(runs_dir)
    rc = driver.main(["--resume", run_dir.name, "--config", str(cfg)])
    assert rc == 1  # clean typed error, not a crash


def test_cli_requires_exactly_one_mode(make_config):
    with pytest.raises(SystemExit):
        driver.parse_args([])
    with pytest.raises(SystemExit):
        driver.parse_args(["question", "--resume", "x"])


def test_eval_fail_with_empty_queue_finishes_clean_stall(make_config, runs_dir, monkeypatch):
    # Observed smoke6 2026-06-10: evaluator FAILs while closing the last open
    # questions -> next worker would crash on an empty queue. The driver must
    # finish cleanly (exhaustion-stall) with a partial report instead.
    from src.state import Verdict

    cfg = make_config()
    real_backend = get_backend

    def exhausting_backend(settings):
        backend = dict(real_backend(settings))
        real_worker = backend["worker"]

        def worker(run, settings_, cycle, ledger_):
            result = real_worker(run, settings_, cycle, ledger_)
            qs = run.load_questions()
            for q in qs.root:
                q.status = "resolved"
            run.save_questions(qs)
            return result

        def evaluator(run, settings_, cycle, ledger_):
            run.write_verdict(
                cycle,
                Verdict(
                    passed=False,
                    unmet_criteria=["a criterion stands unmet"],
                    contradictions=[],
                    new_questions=[],
                    notes="fail with nothing actionable",
                ),
            )
            return backend_result(settings_, cycle, ledger_)

        def backend_result(settings_, cycle, ledger_):
            from src.sessions.stub import _result
            import time as _t

            return _result(settings_, "evaluator", "evaluator", _t.monotonic(), "fail", ledger_, cycle)

        backend["worker"] = worker
        backend["evaluator"] = evaluator
        return backend

    monkeypatch.setattr(driver, "get_backend", exhausting_backend)
    rc = driver.main(["q", "--config", str(cfg)])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.finish_reason == "stall"
    progress = (run_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "zero open questions" in progress
    assert "PARTIAL" in (run_dir / REPORT_FILE).read_text(encoding="utf-8")
