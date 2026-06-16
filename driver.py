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
from src.runspace import PLAN_FILE, REPORT_FILE, Runspace, _atomic_write
from src.profiles import get_profile
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
    parser.add_argument(
        "--comprehensive",
        action="store_true",
        help="deep-research posture: promote the config `comprehensive:` bundle "
        "(more cycles/wall/budget, deeper question tree, more seed questions). "
        "Explicit --max-* flags still win.",
    )
    parser.add_argument(
        "--lens",
        action="append",
        metavar="NAME",
        help="activate an evidence lens (e.g. community); repeatable",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="run the adversarial verification wave before synthesis (an "
        "independent verifier tries to refute each load-bearing finding). "
        "Implied by --comprehensive.",
    )
    parser.add_argument(
        "--budget",
        action="store_true",
        help="cost-optimized posture: swap the config `budget:` role overrides "
        "(local compose, Haiku synthesis/verifier, capped verification) to keep "
        "a comprehensive run under ~$1. Trades some Opus judgment quality.",
    )
    parser.add_argument(
        "--cheap",
        action="store_true",
        help="cheap posture: gpt-oss-120b @ Groq volume + DeepSeek V4 Pro on "
        "init/verify/synth (grounded), and the once-firing gate on Qwen 3.7 Max "
        "(non-hallucinating auditor). ~$0.7-1/run. Needs the proxy + DASHSCOPE.",
    )
    parser.add_argument(
        "--accurate",
        action="store_true",
        help="high-accuracy posture: identical to --cheap but the once-firing gate "
        "is Opus 4.8 (vs Qwen) + more verify passes. Frontier touches only the "
        "gate. ~$1-1.5/run. Requires the LiteLLM/Groq proxy.",
    )
    parser.add_argument(
        "--waves",
        action="store_true",
        help="orchestrate waves: after BREADTH resolves the seed tree, seed a "
        "DEPTH wave that re-investigates the top findings (primary-source "
        "insistence + cross-validation) before verify/synthesis. Implied by "
        "--comprehensive; use this to enable it on a shorter run.",
    )
    parser.add_argument(
        "--json-summary",
        metavar="PATH",
        help="write a machine-readable run summary here (orchestrator hook)",
    )
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


def _verify_phase(
    run: Runspace, settings: Settings, ledger: Ledger, console: Console
) -> None:
    """Adversarial verification wave (COMPREHENSIVE_RESEARCH_SPEC §3): before
    synthesis, an independent verifier tries to REFUTE each load-bearing
    finding; the verdict is written into the finding's meta so the synthesizer
    can demote refuted claims. Opt-in (settings.verification.enabled). Skips
    already-verified findings, so a resumed finish re-enters cleanly. Budget-
    guarded: verification spends Opus, so it stops at the budget breaker rather
    than blowing past it in the breaker-exempt finish path."""
    if not settings.verification.enabled or settings.session.backend != "sdk":
        return
    from src.profiles import get_profile
    from src.sessions import verifier

    vcfg = settings.verification
    findings = run.load_findings()
    candidates = sorted(
        (
            (slug, m, b)
            for slug, (m, b) in findings.items()
            if m.track == "factual"
            and m.verification_status == "unverified"
            and m.confidence >= vcfg.min_confidence
        ),
        key=lambda t: t[1].confidence,
        reverse=True,
    )[: vcfg.max_findings]
    if not candidates:
        return

    profile = get_profile(run.meta.profile)
    cycle = run.last_cycle()
    console.log(f"verification wave: challenging {len(candidates)} findings")
    counts = {"verified": 0, "refuted": 0, "unverified": 0}
    for slug, meta, body in candidates:
        if ledger.spend_usd >= settings.max_budget_usd:
            run.log_decision(
                "verification wave halted: budget breaker reached "
                f"({len(candidates) - sum(counts.values())} findings left unverified)"
            )
            break
        try:
            status, note = verifier.verify_finding(
                run, settings, ledger, cycle, profile, slug, meta, body
            )
        except Exception as exc:  # noqa: BLE001 — one bad verify must not kill the report
            run.log_decision(f"verification of {slug} errored: {exc}")
            continue
        run.write_finding(
            slug,
            meta.model_copy(
                update={"verification_status": status, "verification_note": note}
            ),
            body,
        )
        ledger.checkpoint()
        counts[status] = counts.get(status, 0) + 1
        run.log_decision(f"verification {slug}: {status.upper()} — {note}")
        console.log(f"[verify] {slug}: {status}")
    run.log(
        f"verification wave: {counts['verified']} verified, "
        f"{counts['refuted']} refuted, {counts['unverified']} inconclusive"
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
    verification wave (opt-in) annotates findings, then the synthesizer ALWAYS
    writes a (possibly partial) report — it is the one session exempt from
    breakers, by design (§3.4)."""
    run.log(f"Run ending: {reason}")
    run.mark_finishing(reason)
    _verify_phase(run, settings, ledger, console)
    _run_session(backend, "synthesizer", run, settings, run.last_cycle(), ledger, console)
    run.mark_finished()
    return reason


def _advance_to_depth(run: Runspace, settings: Settings, console: Console) -> bool:
    """Wave orchestration (COMPREHENSIVE_RESEARCH_SPEC item 4). Called at every
    point BREADTH would finish 'conclusive': if waves are on and we're still in
    BREADTH, seed DEPTH questions from the top findings and return True so the
    caller keeps looping (the worker/evaluator machinery resolves them, breakers
    still armed) instead of finishing. Returns False — finish normally — when
    waves are off, we're already in DEPTH, or nothing is worth deepening. This
    is the ONLY new control in the loop; everything else is the existing flow."""
    if not settings.waves.enabled or run.meta.wave != "breadth":
        return False
    from src.sessions.depth import seed_depth_questions

    seeded = seed_depth_questions(run, settings)
    if seeded == 0:
        return False
    run.set_wave("depth")
    run.log_decision(
        f"BREADTH concluded; entering DEPTH wave — seeded {seeded} deepening "
        "question(s) for primary-source re-investigation + cross-validation."
    )
    console.log(f"wave: BREADTH -> DEPTH ({seeded} findings to deepen)")
    return True


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
            # Two-tier evaluation (operator decision 2026-06-10): the run may
            # only END through the final_evaluator gate when one is configured.
            if "final_evaluator" in settings.roles and "final_evaluator" in backend:
                # Opus final-gate firing cap (budget posture's variable cost):
                # once exhausted, accept the local evaluator's pass rather than
                # re-summon Opus — spend stays deterministic, finish stays
                # conclusive. The budget breaker is still the hard net beneath.
                if run.meta.final_eval_count >= settings.max_final_evaluations:
                    run.log_decision(
                        f"Opus final-gate budget ({settings.max_final_evaluations}) "
                        "exhausted; accepting the per-cycle evaluator's pass as "
                        "conclusive (local-judged, not Opus-confirmed this cycle)."
                    )
                    run.complete_cycle(cycle, stalled=False)
                    if _advance_to_depth(run, settings, console):
                        cycle += 1
                        continue
                    return _finish(backend, run, settings, ledger, console, "conclusive")
                tripped = _tripped_breaker(run, settings, ledger, cycle)
                if tripped:
                    return _finish(backend, run, settings, ledger, console, tripped)
                _run_session(backend, "final_evaluator", run, settings, cycle, ledger, console)
                run.bump_final_eval()
                final_verdict = run.latest_verdict()
                if final_verdict is None:
                    raise EvalError(
                        f"final evaluator finished cycle {cycle} without a verdict"
                    )
                if final_verdict.passed and run.no_open_questions():
                    run.complete_cycle(cycle, stalled=False)
                    if _advance_to_depth(run, settings, console):
                        cycle += 1
                        continue
                    return _finish(backend, run, settings, ledger, console, "conclusive")
                # Final gate rejected: its new questions are open now — the
                # loop deepens. State changed, so this cycle is not a stall.
                run.complete_cycle(cycle, stalled=False)
                cycle += 1
                continue
            run.complete_cycle(cycle, stalled=False)
            if _advance_to_depth(run, settings, console):
                cycle += 1
                continue
            return _finish(backend, run, settings, ledger, console, "conclusive")

        if run.no_open_questions():
            # FAIL verdict with an empty queue: the evaluator closed the last
            # open questions without opening new ones (observed smoke6
            # 2026-06-10). Another worker cycle would crash on an empty queue;
            # this is an exhaustion-stall — finish cleanly with the partial
            # report, unmet criteria standing.
            run.log_decision(
                f"evaluator (cycle {cycle}) FAILED with zero open questions — "
                "nothing actionable remains; finishing with a partial report."
            )
            run.complete_cycle(cycle, stalled=False)
            return _finish(backend, run, settings, ledger, console, "stall")

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


def _write_summary(path: str, payload: dict) -> None:
    import json

    _atomic_write(Path(path), json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    console = Console()
    args = parse_args(argv)
    overrides = {
        "max_cycles": args.max_cycles,
        "max_budget_usd": args.max_budget_usd,
        "max_wall_hours": args.max_wall_hours,
        "lenses": args.lens,  # None when unset => config default (empty)
        "comprehensive": args.comprehensive,  # promotes the deep bundle
        "verify": args.verify,  # enables the verification wave
        "waves": args.waves,  # enables BREADTH->DEPTH wave orchestration
        "budget": args.budget,  # swaps in the Haiku role overrides
        "cheap": args.cheap,  # efficient build; once-firing gate on Qwen 3.7 Max
        "accurate": args.accurate,  # same build; once-firing gate on Opus 4.8
    }
    try:
        settings = load_settings(config_path=args.config, overrides=overrides)
        if args.comprehensive:
            console.print(
                f"[bold cyan]COMPREHENSIVE mode — deep bounds applied: "
                f"max_cycles={settings.max_cycles}, "
                f"max_wall_hours={settings.max_wall_hours}, "
                f"max_budget_usd=${settings.max_budget_usd}, "
                f"tree depth<={settings.question_tree.max_depth}, "
                f"<={settings.question_tree.max_questions} questions, "
                f"seed_target={settings.question_tree.seed_target}.[/bold cyan]"
            )
        if settings.is_full_local():
            # §1: full-local is permitted but must be LOUD — judgment roles
            # (evaluator/adjudication/synthesis) degrade most on local models.
            console.print(
                "[bold yellow]WARNING: FULL-LOCAL posture — every role routes to a "
                "non-first-party endpoint. Conclusiveness judgment degrades most "
                "on local models (CLAUDE.md §1); hybrid is the recommended "
                "posture.[/bold yellow]"
            )
        runs_dir = Path(settings.runs_dir)
        if args.resume:
            run = Runspace.resume(runs_dir, args.resume)
            get_profile(run.meta.profile)  # fail fast if unimplemented
            console.log(f"resumed run {run.meta.run_id} at cycle {run.last_cycle() + 1}")
        else:
            profile = args.profile or settings.default_profile
            if profile not in settings.profiles:
                raise ConfigError(
                    f"unknown profile {profile!r}; configured: {settings.profiles}"
                )
            get_profile(profile)  # fail fast if unimplemented
            run = Runspace.create(runs_dir, args.question, profile)
            console.log(f"created run {run.meta.run_id} (profile: {profile})")
            if settings.is_full_local():
                run.log_decision(
                    "run started in FULL-LOCAL posture — all roles on "
                    "non-first-party endpoints (§1 warning issued)"
                )
    except EngineError as exc:
        console.print("error: ", style="red", end="")
        console.print(str(exc), markup=False, highlight=False)
        return 1

    backend = get_backend(settings)
    ledger = Ledger(run)
    try:
        reason = _drive(backend, run, settings, ledger, console)
        _print_summary(run, ledger, reason, console)
        if args.json_summary:
            _write_summary(
                args.json_summary,
                {
                    "status": "finished",
                    "run_id": run.meta.run_id,
                    "run_dir": str(run.root),
                    "question": run.meta.question,
                    "profile": run.meta.profile,
                    "finish_reason": reason,
                    "cycles": run.last_cycle(),
                    "spend_usd": round(ledger.spend_usd, 6),
                    "wall_hours": round(run.wall_hours(), 4),
                    "report": str(run.root / REPORT_FILE),
                },
            )
        return 0
    except EngineError as exc:
        # No silent fallback: surface the error, leave state on disk for --resume.
        console.print("error: ", style="red", end="")
        console.print(str(exc), markup=False, highlight=False)
        console.print(f"run state preserved at {run.root}; resume with --resume {run.meta.run_id}")
        if args.json_summary:
            _write_summary(
                args.json_summary,
                {
                    "status": "error",
                    "run_id": run.meta.run_id,
                    "run_dir": str(run.root),
                    "error": str(exc),
                    "resume_with": run.meta.run_id,
                },
            )
        return 1
    finally:
        run.release_lock()


if __name__ == "__main__":
    sys.exit(main())
