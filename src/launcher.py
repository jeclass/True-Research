"""Cross-platform detached launcher + auto-resume supervisor.

The public replacement for the Windows-only runs/launch_research.ps1
(gitignored local convenience). Two jobs:

1. supervise(): run driver.main() IN-PROCESS — fresh launch captured via
   --run-id-file (never "adopt the newest runs/ dir": audit #16) — then
   auto-resume on ANY non-finished exit (session reap, crash, network blip)
   until runs/<id>/run.json reports finished or attempts are exhausted.
2. spawn_detached(): re-exec this module detached from the controlling
   terminal (Windows DETACHED_PROCESS / POSIX start_new_session) so a
   multi-hour run survives the shell closing.

Usage:
    python -m src.launcher "question" --cheap --verify --detach
    true-research run "question" --cheap --detach        (via src.cli)

Argument order contract: the QUESTION comes FIRST, then flags — the resume
flag extractor treats a bare token after a flag as that flag's value.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class LaunchError(RuntimeError):
    """Launch/supervision failed in a way that must not be silently retried."""


def _driver_main(argv: list[str]) -> int:
    """Indirection point so tests stub the driver without importing the SDK."""
    import driver

    return driver.main(argv)


def _run_status(runs_dir: Path, run_id: str) -> str:
    meta = runs_dir / run_id / "run.json"
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("status", "unknown")
    except (OSError, json.JSONDecodeError):
        return "unreadable"


def supervise(
    driver_args: list[str],
    *,
    runs_dir: Path,
    max_attempts: int = 40,
    sleep_seconds: float = 10.0,
) -> str:
    """Fresh launch + auto-resume loop. Returns the finished run's id.

    driver_args are passed through verbatim (question/--question-file plus any
    flags); flags are RE-PASSED on every resume — run settings rebuild from
    flags, not from state."""
    with tempfile.NamedTemporaryFile("r", suffix=".rid", delete=False) as tf:
        rid_path = Path(tf.name)
    try:
        try:
            rc = _driver_main([*driver_args, "--run-id-file", str(rid_path)])
        except SystemExit as exc:
            # driver.main -> argparse parser.error() raises SystemExit, not an
            # ordinary exception. Convert it so the supervisor exits via the
            # clean "LAUNCH FAILED" path instead of a traceback.
            raise LaunchError(
                f"driver rejected the launch arguments (argparse exit {exc.code}); "
                "nothing to resume"
            ) from exc
        run_id = rid_path.read_text(encoding="utf-8").strip() if rid_path.exists() else ""
    finally:
        rid_path.unlink(missing_ok=True)
    if not run_id:
        # Driver died before Runspace.create (bad flags, import error, config
        # rejection). There is nothing safe to resume — never fall back to an
        # unrelated existing run (audit #16).
        raise LaunchError(
            f"driver produced no run id (exit={rc}) — the launch never reached "
            "Runspace.create; check the log for the real error"
        )

    # Extract the pass-through FLAGS (everything except the question/--question-file)
    flags: list[str] = []
    skip_next = False
    for i, tok in enumerate(driver_args):
        if skip_next:
            skip_next = False
            continue
        if tok == "--question-file":
            skip_next = True
            continue
        if tok.startswith("-"):
            flags.append(tok)
            # keep a flag's value token attached (e.g. --gate opus)
            if i + 1 < len(driver_args) and not driver_args[i + 1].startswith("-"):
                flags.append(driver_args[i + 1])
                skip_next = True
        # bare positional (the question) is dropped for resumes
    for attempt in range(1, max_attempts + 1):
        if _run_status(runs_dir, run_id) == "finished":
            return run_id
        try:
            _driver_main(["--resume", run_id, *flags])
        except SystemExit as exc:
            # An argv that argparse rejects will NEVER succeed — fail loudly
            # once instead of burning max_attempts on a hopeless resume.
            raise LaunchError(
                f"driver rejected the resume arguments (argparse exit {exc.code}) "
                "— flags extracted from the original invocation are malformed; "
                "put the QUESTION FIRST when invoking the launcher"
            ) from exc
        time.sleep(sleep_seconds)
    if _run_status(runs_dir, run_id) == "finished":
        return run_id
    raise LaunchError(
        f"run {run_id} not finished after {max_attempts} attempts "
        f"(status={_run_status(runs_dir, run_id)})"
    )


def spawn_detached(argv: list[str], *, log_path: Path) -> int:
    """Re-exec `python -m src.launcher <argv>` detached from this terminal.
    Returns the child pid. stdout/stderr append to log_path (single encoding
    — the PS1's mixed UTF-8/UTF-16 corruption, audit #18, can't recur)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # child inherits; parent exits — no leak
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": log,
        "cwd": str(Path(__file__).resolve().parents[1]),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "src.launcher", *argv], **kwargs)
    return proc.pid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="src.launcher",
        description="Detached launch + auto-resume supervision for research runs. "
        'Put the QUESTION FIRST, then flags: python -m src.launcher "question" '
        "--cheap --detach",
    )
    parser.add_argument("--detach", action="store_true",
                        help="spawn detached (survives closing this terminal) and exit")
    parser.add_argument("--max-attempts", type=int, default=40)
    parser.add_argument("--log", default="runs/_launcher.log",
                        help="supervisor log file (detached mode)")
    parser.add_argument("--runs-dir", default="runs")
    args, driver_args = parser.parse_known_args(argv)

    if args.detach:
        fwd = list(driver_args)
        if args.max_attempts != 40:
            fwd += ["--max-attempts", str(args.max_attempts)]
        fwd += ["--runs-dir", args.runs_dir, "--log", args.log]
        pid = spawn_detached(fwd, log_path=Path(args.log))
        print(f"detached supervisor pid={pid}; log: {args.log}")
        return 0

    try:
        run_id = supervise(
            driver_args, runs_dir=Path(args.runs_dir), max_attempts=args.max_attempts
        )
    except LaunchError as exc:
        print(f"LAUNCH FAILED: {exc}", file=sys.stderr)
        return 3
    print(f"run {run_id} finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
