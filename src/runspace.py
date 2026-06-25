"""Run directory management: create/resolve runs/<id>/, atomic writes, a
single-driver lock, the stall-detection state hash, and PROGRESS logging
(CLAUDE.md §2, §3.5, §3.6, §3.8).

Atomicity contract: every state write goes through _atomic_write — content is
written to a temp file in the same directory, fsynced, then os.replace()d over
the target. A crash at any point leaves either the old file or the new file,
never a torn one.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src import state
from src.errors import RunspaceError, StateError
from src.state import (
    FindingMeta,
    QuestionList,
    RunMeta,
    SourceRegistry,
    Verdict,
    utcnow,
)

QUESTION_FILE = "QUESTION.md"
PLAN_FILE = "PLAN.md"
QUESTIONS_FILE = "open_questions.yaml"
SOURCES_FILE = "sources.json"
PROGRESS_FILE = "PROGRESS.md"
LEDGER_FILE = "ledger.json"
REPORT_FILE = "REPORT.md"
RUN_META_FILE = "run.json"
FINDINGS_DIR = "findings"
VERDICTS_DIR = "verdicts"
LOCK_FILE = ".lock"

_DECISIONS_HEADING = "## DECISIONS"
_LOG_HEADING = "## Log"


def _atomic_write(target: Path, content: str) -> None:
    """Temp file + fsync + os.replace in the target's directory (invariant 6)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) is not a probe on Windows — it TERMINATES the target
        # (TerminateProcess) and raises plain OSError for dead pids. Probe via
        # a SYNCHRONIZE handle: signaled => exited; timeout/failure => treat as
        # alive (refuse lock takeover when unsure, same posture as the
        # PermissionError branch below).
        import ctypes

        ERROR_ACCESS_DENIED = 5
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            # access denied => live process we may not open; anything else
            # (e.g. ERROR_INVALID_PARAMETER) => no such process
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            return kernel32.WaitForSingleObject(handle, 0) != WAIT_OBJECT_0
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Runspace:
    """Handle to one runs/<id>/ directory. All reads validate; all writes are
    atomic. Holds the driver lock for the lifetime of the object."""

    def __init__(self, root: Path, meta: RunMeta) -> None:
        self.root = root
        self.meta = meta
        self._session_started = time.monotonic()

    # --- construction -------------------------------------------------------

    @classmethod
    def create(cls, runs_dir: Path, question: str, profile: str) -> "Runspace":
        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            + "-"
            + secrets.token_hex(2)
        )
        root = runs_dir / run_id
        if root.exists():
            raise RunspaceError(f"run dir already exists: {root}")
        (root / FINDINGS_DIR).mkdir(parents=True)
        (root / VERDICTS_DIR).mkdir()

        meta = RunMeta(
            run_id=run_id, question=question, profile=profile, created_at=utcnow()
        )
        run = cls(root, meta)
        run._acquire_lock()
        _atomic_write(root / QUESTION_FILE, f"# Research question\n\n{question}\n")
        _atomic_write(
            root / PROGRESS_FILE,
            f"# PROGRESS — run {run_id}\n\n{_LOG_HEADING}\n\n{_DECISIONS_HEADING}\n",
        )
        run._persist_meta()
        return run

    @classmethod
    def resume(cls, runs_dir: Path, run_id: str, *, force: bool = False) -> "Runspace":
        root = runs_dir / run_id
        if not root.is_dir():
            raise RunspaceError(f"no such run: {root}")
        meta = state.parse_run_meta(
            cls._read(root / RUN_META_FILE), label=str(root / RUN_META_FILE)
        )
        if meta.status == "finished" and not force:
            raise RunspaceError(
                f"run {run_id} already finished (reason: {meta.finish_reason}); "
                "start a new run, or pass --force-resume to continue it"
            )
        run = cls(root, meta)
        run._acquire_lock()
        if meta.status == "finished":
            # --force-resume: re-open a finished run to keep researching it (e.g.
            # add budget / new sources after a stall). Reset status so the driver
            # loop runs again; the next finish overwrites finish_reason.
            run.meta = run.meta.model_copy(update={"status": "running"})
            run._persist_meta()
            run.log_decision(
                f"--force-resume: re-opened a finished run (was '{meta.finish_reason}') "
                "to continue researching; status reset to running"
            )
        # Validate everything reconstructable now, so a corrupt file fails the
        # resume loudly instead of mid-cycle (invariant 7).
        run.load_questions()
        run.load_sources()
        run.latest_verdict()
        return run

    @classmethod
    def open_readonly(cls, runs_dir: Path, run_id: str) -> "Runspace":
        """Open a run for READ-ONLY inspection — no lock, no finished-guard.

        For tooling that reads a frozen (usually finished) run without continuing
        it: e.g. the gate A/B replay, which judges one terminal state under
        different models and must never mutate or relock it. The caller MUST NOT
        invoke any write_*/checkpoint method on the returned object, and should
        only point this at terminal runs (it deliberately ignores the lock, so a
        live driver's run would be read mid-write)."""
        root = runs_dir / run_id
        if not root.is_dir():
            raise RunspaceError(f"no such run: {root}")
        meta = state.parse_run_meta(
            cls._read(root / RUN_META_FILE), label=str(root / RUN_META_FILE)
        )
        return cls(root, meta)

    # --- lock ----------------------------------------------------------------

    def _acquire_lock(self) -> None:
        lock = self.root / LOCK_FILE
        if lock.exists():
            try:
                holder = int(lock.read_text(encoding="utf-8").strip())
            except ValueError:
                holder = -1
            if holder > 0 and holder != os.getpid() and _pid_alive(holder):
                raise RunspaceError(
                    f"run {self.meta.run_id} is locked by live pid {holder}; "
                    "refusing to run two drivers against one run"
                )
        _atomic_write(lock, str(os.getpid()))

    def release_lock(self) -> None:
        lock = self.root / LOCK_FILE
        if lock.exists():
            lock.unlink()

    # --- low-level io ---------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> str:
        if not path.is_file():
            raise StateError(f"expected state file missing: {path}")
        return path.read_text(encoding="utf-8")

    def write_text(self, relpath: str, content: str) -> None:
        _atomic_write(self.root / relpath, content)

    # --- run meta / breaker bookkeeping ----------------------------------------

    def _persist_meta(self) -> None:
        _atomic_write(self.root / RUN_META_FILE, state.dump_run_meta(self.meta))

    def wall_hours(self) -> float:
        """Accumulated *active* driver hours: persisted total + this process's
        elapsed time. Idle time between kill and --resume does not count
        (docs/DECISIONS.md)."""
        live = time.monotonic() - self._session_started
        return (self.meta.active_seconds + live) / 3600.0

    def checkpoint_clock(self) -> None:
        now = time.monotonic()
        elapsed = now - self._session_started
        self._session_started = now
        self.meta = self.meta.model_copy(
            update={"active_seconds": self.meta.active_seconds + elapsed}
        )
        self._persist_meta()

    def last_cycle(self) -> int:
        return self.meta.last_cycle

    def bump_final_eval(self) -> int:
        """Count an Opus final-gate firing (persisted; resume-safe)."""
        self.meta = self.meta.model_copy(
            update={"final_eval_count": self.meta.final_eval_count + 1}
        )
        self._persist_meta()
        return self.meta.final_eval_count

    def set_wave(self, wave: str) -> None:
        """Advance the wave phase (breadth -> depth), persisted so an 8-hour
        run resumes into the correct wave (COMPREHENSIVE_RESEARCH_SPEC item 4)."""
        self.meta = self.meta.model_copy(update={"wave": wave})
        self.checkpoint_clock()

    def complete_cycle(self, cycle: int, stalled: bool) -> int:
        """Persist end-of-cycle bookkeeping atomically; returns stall count."""
        stall_count = self.meta.stall_count + 1 if stalled else 0
        self.meta = self.meta.model_copy(
            update={"last_cycle": cycle, "stall_count": stall_count}
        )
        self.checkpoint_clock()
        return stall_count

    def mark_finishing(self, reason: state.FinishReason) -> None:
        """Record the finish reason while the synthesizer still has to run.
        If the process dies mid-synthesis, --resume sees the reason and
        completes the finish instead of looping again."""
        self.meta = self.meta.model_copy(update={"finish_reason": reason})
        self.checkpoint_clock()

    def mark_finished(self) -> None:
        self.meta = self.meta.model_copy(update={"status": "finished"})
        self.checkpoint_clock()

    # --- state files -------------------------------------------------------------

    def load_questions(self) -> QuestionList:
        path = self.root / QUESTIONS_FILE
        if not path.is_file():
            return QuestionList([])
        return state.parse_questions(self._read(path), label=str(path))

    def save_questions(self, questions: QuestionList) -> None:
        self.write_text(QUESTIONS_FILE, state.dump_questions(questions))

    def load_sources(self) -> SourceRegistry:
        path = self.root / SOURCES_FILE
        if not path.is_file():
            return SourceRegistry({})
        return state.parse_sources(self._read(path), label=str(path))

    def save_sources(self, sources: SourceRegistry) -> None:
        self.write_text(SOURCES_FILE, state.dump_sources(sources))

    def write_finding(self, slug: str, meta: FindingMeta, body: str) -> str:
        relpath = f"{FINDINGS_DIR}/{slug}.md"
        self.write_text(relpath, state.dump_finding(meta, body))
        return relpath

    def load_findings(self) -> dict[str, tuple[FindingMeta, str]]:
        findings: dict[str, tuple[FindingMeta, str]] = {}
        for path in sorted((self.root / FINDINGS_DIR).glob("*.md")):
            findings[path.stem] = state.parse_finding(
                self._read(path), label=str(path)
            )
        return findings

    def write_verdict(self, cycle: int, verdict: Verdict, final: bool = False) -> None:
        suffix = "-final" if final else ""
        self.write_text(
            f"{VERDICTS_DIR}/cycle-{cycle}{suffix}.md", state.dump_verdict(verdict)
        )

    def latest_verdict(self) -> Verdict | None:
        """Newest verdict; at the same cycle a -final verdict (the terminal
        Opus gate, two-tier evaluation) supersedes the per-cycle one."""
        best: tuple[int, int, Path] | None = None
        for path in (self.root / VERDICTS_DIR).glob("cycle-*.md"):
            stem = path.stem.removeprefix("cycle-")
            is_final = 1 if stem.endswith("-final") else 0
            if is_final:
                stem = stem.removesuffix("-final")
            try:
                n = int(stem)
            except ValueError as exc:
                raise StateError(f"unexpected verdict filename: {path}") from exc
            if best is None or (n, is_final) > (best[0], best[1]):
                best = (n, is_final, path)
        if best is None:
            return None
        return state.parse_verdict(self._read(best[2]), label=str(best[2]))

    def no_open_questions(self) -> bool:
        questions = self.load_questions()
        return not questions.open_items() and not questions.in_progress_items()

    # --- stall-detection hash (invariant 5) ----------------------------------------

    def state_hash(self) -> str:
        """SHA-256 over open_questions.yaml + findings/ contents only — the two
        artifacts §3.5 names. PROGRESS/ledger/verdict writes do not mask a stall."""
        digest = hashlib.sha256()
        questions_path = self.root / QUESTIONS_FILE
        if questions_path.is_file():
            digest.update(questions_path.read_bytes())
        digest.update(b"\x00")
        for path in sorted((self.root / FINDINGS_DIR).glob("*.md")):
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(path.read_bytes())
            digest.update(b"\x00")
        return digest.hexdigest()

    # --- PROGRESS.md (invariant 8) ---------------------------------------------------

    def _progress_text(self) -> str:
        path = self.root / PROGRESS_FILE
        return self._read(path)

    def log(self, message: str) -> None:
        """Append a timestamped line under '## Log'."""
        line = f"- [{utcnow().isoformat(timespec='seconds')}] {message}"
        text = self._progress_text()
        head, sep, tail = text.partition(_DECISIONS_HEADING)
        if not sep:
            raise StateError(f"{PROGRESS_FILE} is missing the '{_DECISIONS_HEADING}' heading")
        self.write_text(PROGRESS_FILE, f"{head.rstrip()}\n{line}\n\n{sep}{tail}")

    def log_decision(self, message: str) -> None:
        """Append under '## DECISIONS' — consequential choices are never silent."""
        line = f"- [{utcnow().isoformat(timespec='seconds')}] {message}"
        text = self._progress_text()
        self.write_text(PROGRESS_FILE, f"{text.rstrip()}\n{line}\n")

    def decisions(self) -> list[str]:
        text = self._progress_text()
        _, sep, tail = text.partition(_DECISIONS_HEADING)
        if not sep:
            return []
        return [line[2:] for line in tail.splitlines() if line.startswith("- ")]
