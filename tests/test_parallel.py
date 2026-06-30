"""Parallel worker fan-out (roadmap): investigate N questions concurrently per
cycle. Correctness rests on the pipeline's apply sections being await-free, so
asyncio's cooperative scheduler serializes the shared-state writes with no lock."""

import asyncio

from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import common, pipeline
from src.sessions.base import SessionResult
from src.state import (
    FindingMeta,
    OpenQuestion,
    QuestionList,
    SourceRecord,
    SourceRegistry,
)


def test_pick_target_questions_orphans_first_then_top_open():
    qs = QuestionList([
        OpenQuestion(id="q-1", question="a", priority=5, created_by="initializer"),
        OpenQuestion(id="q-2", question="b", priority=3, created_by="initializer",
                     status="in_progress"),
        OpenQuestion(id="q-3", question="c", priority=4, created_by="initializer"),
    ])
    # orphaned in_progress first, then highest-priority open
    assert [q.id for q in common.pick_target_questions(qs, 2)] == ["q-2", "q-1"]
    # k<=1 collapses to exactly the single picker's choice
    assert [q.id for q in common.pick_target_questions(qs, 1)] == ["q-2"]
    assert common.pick_target_questions(qs, 1)[0].id == common.pick_target_question(qs).id


def test_run_pipeline_batch_is_concurrent_and_loses_no_writes(tmp_path, monkeypatch):
    # The load-bearing correctness test: K questions investigated concurrently must
    # (a) genuinely overlap and (b) each apply its finding + resolve WITHOUT a lost
    # update, exactly because the apply is await-free.
    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        k = 3
        run.save_questions(QuestionList([
            OpenQuestion(id=f"q-{i}", question=f"facet {i}", priority=3,
                         created_by="initializer", status="in_progress")
            for i in range(1, k + 1)
        ]))
        reg = SourceRegistry({})
        reg.root["src-x"] = SourceRecord(url="https://x", title="t", kind="web",
                                         credibility=50, retrieved_at=common.utcnow(), notes="")
        run.save_sources(reg)

        gate = {"entered": 0}

        async def fake_async(run_, settings_, cycle_, ledger_, target, profile_):
            # Concurrency proof: every task must ENTER before any proceeds. A
            # sequential runner would spin here forever on the first task; the
            # bounded spin turns that regression into a clean failure, not a hang.
            gate["entered"] += 1
            spins = 0
            while gate["entered"] < k:
                spins += 1
                if spins > 100_000:
                    raise AssertionError("tasks did not run concurrently")
                await asyncio.sleep(0)
            # --- await-free apply, exactly like the real pipeline's tail ---
            slug = f"{target.id}-c{cycle_:02d}"
            run_.write_finding(slug, FindingMeta(question_id=target.id,
                               source_ids=["src-x"], confidence=0.8), "body [src-x]")
            questions = run_.load_questions()
            fresh = questions.get(target.id)
            fresh.status = "resolved"
            run_.save_questions(questions)
            return SessionResult(session_type="worker", model="m", endpoint="e",
                                 input_tokens=1, output_tokens=1, cached_tokens=0,
                                 usd=0.0, wall_seconds=0.1, summary=f"resolved {target.id}")

        monkeypatch.setattr(pipeline, "_run_pipeline_async", fake_async)
        targets = common.pick_target_questions(run.load_questions(), k)
        results = pipeline.run_pipeline_batch(run, None, 1, Ledger(run), targets, None)

        assert len(results) == k
        assert all(isinstance(r, SessionResult) for r in results)   # none errored
        final = run.load_questions()
        assert all(q.status == "resolved" for q in final.root)      # NO lost update
        assert len(list((run.root / "findings").glob("*.md"))) == k  # all findings written
    finally:
        run.release_lock()


def test_run_pipeline_batch_one_failure_does_not_kill_the_batch(tmp_path, monkeypatch):
    # return_exceptions=True: one question raising leaves the others intact.
    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        run.save_questions(QuestionList([
            OpenQuestion(id="q-ok", question="a", priority=3, created_by="initializer",
                         status="in_progress"),
            OpenQuestion(id="q-bad", question="b", priority=3, created_by="initializer",
                         status="in_progress"),
        ]))

        async def fake_async(run_, settings_, cycle_, ledger_, target, profile_):
            if target.id == "q-bad":
                raise RuntimeError("compose blew up")
            return SessionResult(session_type="worker", model="m", endpoint="e",
                                 input_tokens=0, output_tokens=0, cached_tokens=0,
                                 usd=0.0, wall_seconds=0.1, summary="ok")

        monkeypatch.setattr(pipeline, "_run_pipeline_async", fake_async)
        targets = common.pick_target_questions(run.load_questions(), 2)
        results = pipeline.run_pipeline_batch(run, None, 1, Ledger(run), targets, None)

        kinds = {t.id: type(r).__name__ for t, r in zip(targets, results)}
        assert kinds["q-ok"] == "SessionResult"
        assert isinstance(dict(zip([t.id for t in targets], results))["q-bad"], RuntimeError)
    finally:
        run.release_lock()


def test_worker_run_parallel_marks_k_in_progress_and_combines(make_config, tmp_path, monkeypatch):
    # the worker.run branch: parallel mode dispatches exactly k targets, marks them
    # in_progress before the batch, and returns one combined SessionResult.
    from src.sessions import worker
    from src.settings import load_settings

    cfg = make_config(**{"worker_pipeline.enabled": True,
                         "worker_pipeline.parallel_questions": 2})
    settings = load_settings(config_path=str(cfg))
    run = Runspace.create(tmp_path / "prun", "q", "general")
    try:
        run.save_questions(QuestionList([
            OpenQuestion(id=f"q-{i}", question=f"f{i}", priority=3, created_by="initializer")
            for i in range(1, 4)
        ]))
        captured = {}

        def fake_batch(run_, s_, c_, l_, targets, profile_):
            captured["targets"] = [t.id for t in targets]
            # by now the worker must already have persisted the in_progress marks
            captured["in_progress"] = sorted(
                q.id for q in run_.load_questions().root if q.status == "in_progress"
            )
            return [SessionResult(session_type="worker", model="m", endpoint="e",
                                  input_tokens=1, output_tokens=1, cached_tokens=0,
                                  usd=0.0, wall_seconds=0.1, summary="ok")
                    for _ in targets]

        monkeypatch.setattr(pipeline, "run_pipeline_batch", fake_batch)
        result = worker.run(run, settings, 1, Ledger(run))

        assert len(captured["targets"]) == 2          # exactly k dispatched
        assert captured["in_progress"] == captured["targets"]  # marked before the batch
        assert "parallel: 2/2" in result.summary
    finally:
        run.release_lock()
