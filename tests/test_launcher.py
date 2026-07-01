"""Cross-platform detached launcher + auto-resume supervisor (v1 gate item 1.2).
All tests are hermetic: driver.main is stubbed; no processes are spawned."""

import json
import sys
from pathlib import Path

import pytest

from src import launcher


def _write_run(runs_dir: Path, run_id: str, status: str) -> None:
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({"status": status}), encoding="utf-8")


def test_supervise_launches_then_resumes_until_finished(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    calls = []

    def fake_driver_main(argv):
        calls.append(list(argv))
        if "--resume" not in argv:               # fresh launch: create the run
            _write_run(runs_dir, "run-001", "running")
            idx = argv.index("--run-id-file")
            Path(argv[idx + 1]).write_text("run-001\n", encoding="utf-8")
            return 1                              # died mid-run (reaped/crash)
        # first resume finishes the run
        _write_run(runs_dir, "run-001", "finished")
        return 0

    monkeypatch.setattr(launcher, "_driver_main", fake_driver_main)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)

    run_id = launcher.supervise(
        ["the question", "--cheap"], runs_dir=runs_dir, max_attempts=5
    )
    assert run_id == "run-001"
    assert "--resume" not in calls[0] and "the question" in calls[0]
    assert calls[1][:2] == ["--resume", "run-001"]
    assert "--cheap" in calls[1]                  # flags re-passed on resume
    assert len(calls) == 2                        # stopped as soon as finished


def test_supervise_gives_up_after_max_attempts(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"

    def stuck_driver_main(argv):
        if "--resume" not in argv:
            _write_run(runs_dir, "run-002", "running")
            idx = argv.index("--run-id-file")
            Path(argv[idx + 1]).write_text("run-002\n", encoding="utf-8")
        return 1                                  # never finishes

    monkeypatch.setattr(launcher, "_driver_main", stuck_driver_main)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)

    with pytest.raises(launcher.LaunchError, match="attempts"):
        launcher.supervise(["q"], runs_dir=runs_dir, max_attempts=3)


def test_supervise_fails_loudly_when_no_run_created(tmp_path, monkeypatch):
    # Mirrors the PS1 fix (audit #16): if driver dies before Runspace.create,
    # never adopt an unrelated run — fail loudly.
    monkeypatch.setattr(launcher, "_driver_main", lambda argv: 2)
    with pytest.raises(launcher.LaunchError, match="no run id"):
        launcher.supervise(["q"], runs_dir=tmp_path / "runs", max_attempts=3)


def test_supervise_converts_argparse_rejection_to_launch_error(tmp_path, monkeypatch):
    # driver.main -> parser.error -> SystemExit(2). supervise() must convert
    # that to LaunchError so the (detached) supervisor exits via the clean
    # "LAUNCH FAILED" path instead of dying with a traceback.
    def rejecting_driver_main(argv):
        raise SystemExit(2)

    monkeypatch.setattr(launcher, "_driver_main", rejecting_driver_main)
    with pytest.raises(launcher.LaunchError, match="rejected the launch"):
        launcher.supervise(["--bogus"], runs_dir=tmp_path / "runs", max_attempts=3)


def test_supervise_resume_rejection_fails_loudly_not_crash(tmp_path, monkeypatch):
    # Flag-before-question invocations make the flag extractor consume the
    # question as a flag value; the resume argv then trips driver argparse
    # (positional question + --resume). That must fail loudly ONCE — not crash
    # with a traceback, and not spin the retry loop on a hopeless argv.
    runs_dir = tmp_path / "runs"
    resume_calls = []

    def driver_main(argv):
        if "--resume" not in argv:
            _write_run(runs_dir, "run-003", "running")
            idx = argv.index("--run-id-file")
            Path(argv[idx + 1]).write_text("run-003\n", encoding="utf-8")
            return 1
        resume_calls.append(list(argv))
        raise SystemExit(2)

    monkeypatch.setattr(launcher, "_driver_main", driver_main)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)

    with pytest.raises(launcher.LaunchError, match="QUESTION FIRST"):
        launcher.supervise(
            ["--cheap", "my question"], runs_dir=runs_dir, max_attempts=40
        )
    assert len(resume_calls) == 1                 # no retry loop on bad argv


def test_spawn_detached_uses_platform_flags(tmp_path, monkeypatch):
    captured = {}

    class FakeProc:
        pid = 4242

    def fake_popen(argv, **kw):
        captured["argv"] = argv
        captured.update(kw)
        return FakeProc()

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    pid = launcher.spawn_detached(["arg1"], log_path=tmp_path / "x.log")
    assert pid == 4242
    assert captured["argv"][0] == sys.executable
    assert captured["argv"][1:3] == ["-m", "src.launcher"]
    assert "arg1" in captured["argv"]
    if sys.platform == "win32":
        assert captured["creationflags"] & launcher.subprocess.DETACHED_PROCESS
    else:
        assert captured["start_new_session"] is True


def test_main_detach_reexecs_self_without_detach_flag(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        launcher, "spawn_detached",
        lambda argv, log_path: seen.update(argv=argv, log=log_path) or 7,
    )
    rc = launcher.main(["the q", "--detach", "--cheap", "--log", str(tmp_path / "l.log")])
    assert rc == 0
    assert "--detach" not in seen["argv"]
    assert "the q" in seen["argv"] and "--cheap" in seen["argv"]
