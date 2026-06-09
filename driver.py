"""Marathon Research Engine — deterministic driver loop (CLAUDE.md §5).

This file contains ZERO prompt text and ZERO model calls. All cognition lives
in session modules selected via src.sessions.get_backend(). The loop's job:
breakers before every session, the stall guard, atomic bookkeeping, and a
partial report on every exit path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.errors import ConfigError, EngineError
from src.ledger import Ledger
from src.runspace import PLAN_FILE, REPORT_FILE, Runspace
from src.sessions import Backend, get_backend
from src.sessions.base import EvalError
from src.settings import Settings, load_settings
from src.state import FinishReason


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="driver", description="Run or resume a marathon research run."
    )
    parser.add_argument("question", nargs="?", help="research question for a new run")
    parser.add_argument("--resume", metavar="RUN_ID", help="resume an existing run")
    parser.add_argument("--profile", help="research profile (default from config)")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--max-cycles", type=int, dest="max_cycles")
    parser.add_argument("--max-budget-usd", type=float, dest="max_budget_usd")
    parser.add_argument("--max-wall-hours", type=float, dest="max_wall_hours")
    args = parser.parse_args(argv)
    if bool(args.question) == bool(args.resume):
        parser.error("provide exactly one of: a question, or --resume RUN_ID")
    return args


def _tripped_breaker(
    run: Runspace, settings: Settings, ledger: Ledger, cycle: int
) -> FinishReason | None:
    """Checked before EVERY session (invariant 4). Order: budget, time, cycles."""
    if ledger.spend_usd >= settings.max_budget_usd:
        return "budget"
    if run.wall_hours() >= settings.max_wall_hours:
        return "time"
    if cycle > settings.max_cycles:
        return "max_cycles"
    return None


def _run_session(
    backend: Backend,
    name: str,
    run: Runspace,
    settings: Settings,
    cycle: int,
    ledger: Ledger,
    console: Console,
) -> None:
    console.log(f"[cycle {cycle}] {name}: starting")
    # Sessions record their own ledger entries (so a failed session still
    # accounts its spend); the driver only checkpoints and reads totals.
    result = backend[name](run, settings, cycle, ledger)
    ledger.checkpoint()
    console.log(
        f"[cycle {cycle}] {name}: {result.summary} "
        f"(${result.usd:.4f}, {result.wall_seconds:.1f}s, run total ${ledger.spend_usd:.4f})"
    )


def _finish(
    backend: Backend,
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    console: Console,
    reason: FinishReason,
) -> FinishReason:
    """Every exit path lands here: reason is recorded first, then the
    synthesizer ALWAYS writes a (possibly partial) report — it is the one
    session exempt from breakers, by design (§3.4)."""
    run.log(f"Run ending: {reason}")
    run.mark_finishing(reason)
    _run_session(backend, "synthesizer", run, settings, run.last_cycle(), ledger, console)
    run.mark_finished()
    return reason


def _drive(
    backend: Backend,
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    console: Console,
) -> FinishReason:
    # A finish that was interrupted mid-synthesis resumes straight to finish.
    if run.meta.finish_reason is not None:
        console.log(f"resuming an interrupted finish (reason: {run.meta.finish_reason})")
        return _finish(backend, run, settings, ledger, console, run.meta.finish_reason)

    if not (run.root / PLAN_FILE).is_file():
        tripped = _tripped_breaker(run, settings, ledger, cycle=1)
        if tripped:
            return _finish(backend, run, settings, ledger, console, tripped)
        _run_session(backend, "initializer", run, settings, 0, ledger, console)

    cycle = run.last_cycle() + 1
    while True:
        tripped = _tripped_breaker(run, settings, ledger, cycle)
        if tripped:
            return _finish(backend, run, settings, ledger, console, tripped)

        before = run.state_hash()
        _run_session(backend, "worker", run, settings, cycle, ledger, console)

        tripped = _tripped_breaker(run, settings, ledger, cycle)
        if tripped:
            return _finish(backend, run, settings, ledger, console, tripped)
        _run_session(backend, "evaluator", run, settings, cycle, ledger, console)

        verdict = run.latest_verdict()
        if verdict is None:
            raise EvalError(f"evaluator finished cycle {cycle} without writing a verdict")

        if verdict.passed and run.no_open_questions():
            run.complete_cycle(cycle, stalled=False)
            return _finish(backend, run, settings, ledger, console, "conclusive")

        stalled = run.state_hash() == before
        stall_count = run.complete_cycle(cycle, stalled)
        if stalled:
            run.log_decision(
                f"STALL: cycle {cycle} produced no change to open_questions.yaml "
                f"or findings/ ({stall_count}/{settings.stall_cycles} consecutive)."
            )
            if stall_count >= settings.stall_cycles:
                run.log_decision(
                    f"STALL: threshold of {settings.stall_cycles} consecutive "
                    "no-delta cycles reached; halting per invariant 5."
                )
                return _finish(backend, run, settings, ledger, console, "stall")
        cycle += 1


def _print_summary(
    run: Runspace, ledger: Ledger, reason: FinishReason, console: Console
) -> None:
    table = Table(title=f"Run {run.meta.run_id} — {reason}")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("question", run.meta.question)
    table.add_row("profile", run.meta.profile)
    table.add_row("finish reason", reason)
    table.add_row("cycles completed", str(run.last_cycle()))
    table.add_row("sessions ledgered", str(len(ledger.entries)))
    table.add_row("spend (client-side estimate)", f"${ledger.spend_usd:.4f}")
    table.add_row("active wall hours", f"{run.wall_hours():.3f}")
    table.add_row("report", str(run.root / REPORT_FILE))
    console.print(table)


def main(argv: list[str] | None = None) -> int:
    console = Console()
    args = parse_args(argv)
    overrides = {
        "max_cycles": args.max_cycles,
        "max_budget_usd": args.max_budget_usd,
        "max_wall_hours": args.max_wall_hours,
    }
    try:
        settings = load_settings(config_path=args.config, overrides=overrides)
        runs_dir = Path(settings.runs_dir)
        if args.resume:
            run = Runspace.resume(runs_dir, args.resume)
            console.log(f"resumed run {run.meta.run_id} at cycle {run.last_cycle() + 1}")
        else:
            profile = args.profile or settings.default_profile
            if profile not in settings.profiles:
                raise ConfigError(
                    f"unknown profile {profile!r}; configured: {settings.profiles}"
                )
            run = Runspace.create(runs_dir, args.question, profile)
            console.log(f"created run {run.meta.run_id} (profile: {profile})")
    except EngineError as exc:
        console.print(f"[red]error:[/red] {exc}")
        return 1

    backend = get_backend(settings)
    ledger = Ledger(run)
    try:
        reason = _drive(backend, run, settings, ledger, console)
        _print_summary(run, ledger, reason, console)
        return 0
    except EngineError as exc:
        # No silent fallback: surface the error, leave state on disk for --resume.
        console.print(f"[red]error:[/red] {exc}")
        console.print(f"run state preserved at {run.root}; resume with --resume {run.meta.run_id}")
        return 1
    finally:
        run.release_lock()


if __name__ == "__main__":
    sys.exit(main())
