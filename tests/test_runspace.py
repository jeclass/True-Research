"""Atomic-write crash safety, the stall hash, and lock semantics."""

import os
from pathlib import Path

import pytest

from src import runspace as runspace_mod
from src.errors import RunspaceError
from src.runspace import Runspace, _atomic_write
from src.state import OpenQuestion, QuestionList


@pytest.fixture
def run(tmp_path: Path) -> Runspace:
    r = Runspace.create(tmp_path / "runs", "test question", "general")
    yield r
    r.release_lock()


def test_atomic_write_survives_simulated_crash(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    _atomic_write(target, "ORIGINAL")

    def exploding_replace(src, dst):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", exploding_replace)
    with pytest.raises(OSError, match="simulated crash"):
        _atomic_write(target, "NEW CONTENT")
    monkeypatch.undo()

    # The original file is intact and no temp debris is left behind.
    assert target.read_text() == "ORIGINAL"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_replaces_on_success(tmp_path):
    target = tmp_path / "state.json"
    _atomic_write(target, "v1")
    _atomic_write(target, "v2")
    assert target.read_text() == "v2"
    assert list(tmp_path.glob("*.tmp")) == []


def test_state_hash_tracks_questions_and_findings_only(run):
    h0 = run.state_hash()

    run.log("progress entries must not change the stall hash")
    assert run.state_hash() == h0

    run.save_questions(
        QuestionList(
            [OpenQuestion(id="q-001", question="x", priority=3, created_by="initializer")]
        )
    )
    h1 = run.state_hash()
    assert h1 != h0

    from src.state import FindingMeta

    run.write_finding(
        "q-001-f", FindingMeta(question_id="q-001", source_ids=["s"], confidence=0.5), "b"
    )
    assert run.state_hash() != h1


def test_lock_blocks_second_live_driver(run, tmp_path):
    # Simulate another live driver holding the lock: PID 1 is always alive.
    (run.root / runspace_mod.LOCK_FILE).write_text("1")
    with pytest.raises(RunspaceError, match="locked by live pid"):
        Runspace.resume(tmp_path / "runs", run.meta.run_id)


def test_stale_lock_is_taken_over(run, tmp_path):
    # A pid that cannot exist: max pid + 1 territory. Use one we spawned and reaped.
    import subprocess

    proc = subprocess.Popen(["true"])
    proc.wait()
    (run.root / runspace_mod.LOCK_FILE).write_text(str(proc.pid))
    resumed = Runspace.resume(tmp_path / "runs", run.meta.run_id)
    assert resumed.meta.run_id == run.meta.run_id
    resumed.release_lock()


def test_resume_refuses_finished_run(run, tmp_path):
    run.mark_finishing("conclusive")
    run.mark_finished()
    run.release_lock()
    with pytest.raises(RunspaceError, match="already finished"):
        Runspace.resume(tmp_path / "runs", run.meta.run_id)


def test_resume_rejects_corrupt_state_loudly(run, tmp_path):
    (run.root / runspace_mod.QUESTIONS_FILE).write_text("{[corrupt", encoding="utf-8")
    run.release_lock()
    from src.errors import StateError

    with pytest.raises(StateError, match="failed validation"):
        Runspace.resume(tmp_path / "runs", run.meta.run_id)
