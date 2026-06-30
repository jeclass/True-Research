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


def test_question_file_loads_quote_laden_question_intact(tmp_path):
    # Root-cause fix 2026-06-30: a question with embedded double-quotes (e.g.
    # 'FORMAT as "NEW -- test this"') does not survive PowerShell 5.1 native-
    # command tokenization — it split into 13 argv tokens and driver.py exited 2
    # with no run dir (silent launch failure). --question-file sidesteps the shell
    # entirely: arbitrary quotes/newlines/unicode come through byte-for-byte.
    q = 'Build a strategy. FORMAT as "NEW -- test this" or "BEST PRACTICE".\nLine two: <=35% target.'
    qf = tmp_path / "q.txt"
    qf.write_text(q, encoding="utf-8")
    args = driver.parse_args(["--question-file", str(qf), "--cheap", "--gate", "opus"])
    assert args.question == q.strip()
    assert args.gate == "opus" and args.cheap is True


def test_question_file_rejects_conflicts_and_bad_input(tmp_path):
    # both positional + file is ambiguous; empty file / missing file fail loudly
    # (parser.error -> SystemExit), never silently launching a blank-question run.
    qf = tmp_path / "q.txt"
    qf.write_text("a real question", encoding="utf-8")
    with pytest.raises(SystemExit):
        driver.parse_args(["positional q", "--question-file", str(qf)])
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(SystemExit):
        driver.parse_args(["--question-file", str(empty)])
    with pytest.raises(SystemExit):
        driver.parse_args(["--question-file", str(tmp_path / "nonexistent.txt")])


def test_eval_fail_with_empty_queue_finishes_exhausted(make_config, runs_dir, monkeypatch):
    # Observed smoke6 2026-06-10: evaluator FAILs while closing the last open
    # questions -> next worker would crash on an empty queue. The driver must
    # finish cleanly with a partial report instead. Audit #19: this exhaustion
    # condition gets finish_reason "exhausted" (NOT "stall") so run.json alone
    # distinguishes it from the invariant-5 hash-stall.
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
    assert meta.finish_reason == "exhausted"   # audit #19: distinct from "stall"
    assert meta.stall_count == 0               # exhaustion never trips the hash-stall counter
    progress = (run_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "zero open questions" in progress
    assert "PARTIAL" in (run_dir / REPORT_FILE).read_text(encoding="utf-8")


def test_final_gate_reject_without_questions_finishes_exhausted(make_config, runs_dir, monkeypatch):
    # Audit #0: when the Opus final gate REJECTS (passed=False) but opens no
    # actionable questions and the queue is already empty, the driver used to
    # assert "state changed" and loop — re-summoning the single most expensive
    # call in the system on identical state until the firing cap (default 2)
    # forced acceptance, burning ~2 needless Opus gates. It must instead finish
    # cleanly as "exhausted" on the FIRST such rejection, gate fired exactly once.
    import time as _t

    from src.sessions.stub import _result
    from src.state import Verdict

    cfg = make_config(
        **{
            "roles.final_evaluator": {
                "endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 24,
            },
            "max_final_evaluations": 2,
        }
    )
    real_backend = get_backend
    fired = {"n": 0}

    def rejecting_backend(settings):
        backend = dict(real_backend(settings))
        real_worker = backend["worker"]

        def worker(run, settings_, cycle, ledger_):
            result = real_worker(run, settings_, cycle, ledger_)
            qs = run.load_questions()
            for q in qs.root:
                q.status = "resolved"
            run.save_questions(qs)
            return result

        def evaluator(run, settings_, cycle, ledger_):  # per-cycle gate: PASS
            run.write_verdict(cycle, Verdict(passed=True, unmet_criteria=[],
                              contradictions=[], new_questions=[], notes="cycle pass"))
            return _result(settings_, "evaluator", "evaluator", _t.monotonic(), "ok", ledger_, cycle)

        def final_evaluator(run, settings_, cycle, ledger_):  # terminal gate: REJECT, no Qs
            fired["n"] += 1
            run.write_verdict(cycle, Verdict(passed=False, unmet_criteria=["unmet"],
                              contradictions=[], new_questions=[],
                              notes="reject, nothing actionable"), final=True)
            return _result(settings_, "evaluator", "final_evaluator",
                           _t.monotonic(), "fail", ledger_, cycle)

        backend["worker"] = worker
        backend["evaluator"] = evaluator
        backend["final_evaluator"] = final_evaluator
        return backend

    monkeypatch.setattr(driver, "get_backend", rejecting_backend)
    rc = driver.main(["q", "--config", str(cfg)])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.finish_reason == "exhausted"
    assert fired["n"] == 1  # finished on the FIRST rejection — did NOT loop to the cap
    progress = (run_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "nothing to deepen" in progress


def test_read_outage_streak_trips_clean_breaker(make_config, runs_dir, monkeypatch):
    # audit #20: under a full volume/reader-endpoint outage every fetch fails, so
    # pages_read=0 and the >=3 hard-block never fires — only soft-blocks, whose
    # per-question state delta ALSO hides the outage from the hash-stall guard. The
    # run would churn its whole budget at zero findings. A dedicated streak breaker
    # must stop it cleanly with finish_reason "read_outage".
    import time as _t

    from src.sessions import common
    from src.sessions.stub import _result
    from src.state import FindingMeta, SourceRecord, SourceRegistry, Verdict

    cfg = make_config(**{"max_read_outage_cycles": 2})
    real_backend = get_backend

    def outage_backend(settings):
        backend = dict(real_backend(settings))

        def worker(run, settings_, cycle, ledger_):
            # mimic a soft-block cycle: state changes (so the hash-stall guard
            # won't fire) but EVERY read failed -> the outage signal accrues. The
            # finding cites a registered source so synthesis (invariant 3) is clean.
            reg = run.load_sources()
            reg.root.setdefault("src-x", SourceRecord(
                url="https://x", title="t", kind="web", credibility=50,
                retrieved_at=common.utcnow(), notes=""))
            run.save_sources(reg)
            run.write_finding(
                f"q-001-c{cycle:02d}",
                FindingMeta(question_id="q-001", source_ids=["src-x"], confidence=0.4),
                f"cycle {cycle}: all reads failed (endpoint down) [src-x].",
            )
            run.note_read_outage(True)
            return _result(settings_, "worker", "worker", _t.monotonic(), "outage", ledger_, cycle)

        def evaluator(run, settings_, cycle, ledger_):
            run.write_verdict(cycle, Verdict(passed=False, unmet_criteria=["no evidence"],
                              contradictions=[], new_questions=[], notes="fail; questions still open"))
            return _result(settings_, "evaluator", "evaluator", _t.monotonic(), "fail", ledger_, cycle)

        backend["worker"] = worker
        backend["evaluator"] = evaluator
        return backend

    monkeypatch.setattr(driver, "get_backend", outage_backend)
    rc = driver.main(["q", "--config", str(cfg)])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.finish_reason == "read_outage"
    assert meta.read_outage_streak == 2          # tripped exactly at the cap
    assert meta.last_cycle == 2                  # stopped promptly, didn't churn budget
    progress = (run_dir / "PROGRESS.md").read_text(encoding="utf-8")
    assert "read-endpoint outage" in progress
    assert "PARTIAL" in (run_dir / REPORT_FILE).read_text(encoding="utf-8")


def test_read_outage_streak_resets_when_a_read_succeeds(tmp_path):
    # The breaker must only fire on SUSTAINED total failure — a single good cycle
    # resets the streak (audit #20: ">1 so a transient blip doesn't trip it").
    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        assert run.note_read_outage(True) == 1
        assert run.note_read_outage(True) == 2
        assert run.note_read_outage(False) == 0   # a cycle that read something resets it
        assert run.note_read_outage(True) == 1
    finally:
        run.release_lock()


def test_resume_with_empty_queue_skips_worker_and_finishes(make_config, runs_dir, monkeypatch):
    # Root-cause fix 2026-06-25: a run interrupted between the worker resolving the
    # LAST open question and the evaluator's conclusive-exit check, on resume, used
    # to re-enter at the worker -> "invoked with no open or in_progress questions"
    # -> exit 1, crash-looping the launcher (cost frozen, never finishing). The
    # driver must SKIP the worker on an empty queue and finish via the evaluator.
    import time as _t

    from src.sessions.stub import _result
    from src.state import Verdict

    cfg = make_config()
    real_backend = get_backend

    def make_backend(*, crash_eval):
        def factory(settings):
            backend = dict(real_backend(settings))
            real_worker = backend["worker"]

            def worker(run, settings_, cycle, ledger_):
                result = real_worker(run, settings_, cycle, ledger_)
                qs = run.load_questions()  # resolve EVERY question this cycle
                for q in qs.root:
                    q.status = "resolved"
                run.save_questions(qs)
                return result

            def evaluator(run, settings_, cycle, ledger_):
                if crash_eval:  # interruption AFTER the last question resolved
                    raise RuntimeError("simulated kill before conclusive check")
                run.write_verdict(cycle, Verdict(
                    passed=True, unmet_criteria=[], contradictions=[],
                    new_questions=[], notes="all resolved",
                ))
                return _result(settings_, "evaluator", "evaluator", _t.monotonic(),
                               "pass", ledger_, cycle)

            backend["worker"] = worker
            backend["evaluator"] = evaluator
            return backend

        return factory

    # First run: resolve all questions, then crash in the evaluator -> the run is
    # left "running" with an empty actionable queue (the bug's precondition).
    monkeypatch.setattr(driver, "get_backend", make_backend(crash_eval=True))
    with pytest.raises(RuntimeError, match="simulated kill"):
        driver.main(["q", "--config", str(cfg), "--max-cycles", "5"])
    monkeypatch.undo()

    run_dir = only_run_dir(runs_dir)
    assert _meta(run_dir).status == "running"

    # Resume: the driver must skip the worker (empty queue) and finish conclusively
    # through the evaluator — NOT crash-loop on the empty-queue worker.
    monkeypatch.setattr(driver, "get_backend", make_backend(crash_eval=False))
    rc = driver.main(["--resume", run_dir.name, "--config", str(cfg), "--max-cycles", "5"])
    monkeypatch.undo()

    assert rc == 0
    meta = _meta(run_dir)
    assert meta.status == "finished" and meta.finish_reason == "conclusive"
    assert (run_dir / REPORT_FILE).is_file()
    assert "skipped — no open questions" in (run_dir / "PROGRESS.md").read_text(encoding="utf-8")
