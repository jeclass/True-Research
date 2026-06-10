"""STUB sessions — Phase 1 only. Zero LLM calls, zero SDK imports.

Each stub exercises the REAL state machinery (questions, sources, findings,
verdicts, PROGRESS) with clearly-canned content so the driver loop, breakers,
stall guard, atomic writes, and resume can be proven before any model is
involved. Selected via `session.backend: stub` in config.yaml; every artifact
they write is labeled STUB so nothing can masquerade as research.
"""

from __future__ import annotations

import time

from src.ledger import Ledger
from src.runspace import PLAN_FILE, Runspace
from src.sessions.base import (
    SessionResult,
    SynthesisError,
)
from src.settings import SessionType, Settings
from src.state import (
    FindingMeta,
    LedgerEntry,
    OpenQuestion,
    QuestionList,
    SourceRecord,
    Verdict,
    utcnow,
)

_STUB_BANNER = "_(stub output — Phase 1 plumbing test, not research)_"


def _result(
    settings: Settings,
    session_type: SessionType,
    role: str,
    started: float,
    summary: str,
    ledger: Ledger,
    cycle: int,
) -> SessionResult:
    role_cfg = settings.roles[role]
    ledger.record(
        LedgerEntry(
            cycle=cycle,
            session_type=session_type,
            model=role_cfg.model,
            endpoint=role_cfg.endpoint,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            usd=settings.stub.cost_usd,
            wall_seconds=time.monotonic() - started,
        )
    )
    return SessionResult(
        session_type=session_type,
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        input_tokens=0,
        output_tokens=0,
        cached_tokens=0,
        usd=settings.stub.cost_usd,
        wall_seconds=time.monotonic() - started,
        summary=summary,
    )


def run_initializer(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    started = time.monotonic()
    time.sleep(settings.stub.sleep_seconds)

    count = settings.stub.seed_questions
    questions = QuestionList(
        [
            OpenQuestion(
                id=f"q-{i:03d}",
                question=f"STUB seed question {i} for: {run.meta.question}",
                priority=max(1, 5 - (i - 1)),
                created_by="initializer",
            )
            for i in range(1, count + 1)
        ]
    )
    run.save_questions(questions)
    run.write_text(
        PLAN_FILE,
        f"# PLAN {_STUB_BANNER}\n\n"
        f"Investigate {count} canned questions about: {run.meta.question}\n",
    )
    run.log(f"initializer (stub): wrote PLAN.md + {count} seed questions")
    return _result(settings, "initializer", "initializer", started, f"seeded {count} questions", ledger, cycle)


def run_worker(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    started = time.monotonic()
    time.sleep(settings.stub.sleep_seconds)

    if settings.stub.worker_no_delta:
        run.log(f"worker (stub, cycle {cycle}): forced no-delta — touched nothing")
        return _result(settings, "worker", "worker", started, "forced no-delta", ledger, cycle)

    questions = run.load_questions()
    # Highest priority open question; fall back to an in_progress one so a run
    # killed mid-cycle re-picks the orphaned question on resume.
    candidates = questions.open_items() or questions.in_progress_items()
    if not candidates:
        run.log(f"worker (stub, cycle {cycle}): no open questions left")
        return _result(settings, "worker", "worker", started, "nothing open", ledger, cycle)
    target = sorted(candidates, key=lambda q: (-q.priority, q.id))[0]

    target.status = "in_progress"
    run.save_questions(questions)

    source_id = f"src-{target.id}"
    sources = run.load_sources()
    sources.root[source_id] = SourceRecord(
        url=f"https://example.invalid/{target.id}",
        title=f"STUB source for {target.id}",
        kind="web",
        credibility=50,
        retrieved_at=utcnow(),
    )
    run.save_sources(sources)

    slug = f"{target.id}-stub"
    run.write_finding(
        slug,
        FindingMeta(question_id=target.id, source_ids=[source_id], confidence=0.5),
        f"# Finding for {target.id} {_STUB_BANNER}\n\n"
        f"Canned answer to: {target.question} [{source_id}]",
    )

    target.status = "resolved"
    target.resolved_by_finding = slug
    run.save_questions(questions)
    run.log(f"worker (stub, cycle {cycle}): resolved {target.id} -> findings/{slug}.md")
    return _result(settings, "worker", "worker", started, f"resolved {target.id}", ledger, cycle)


def run_evaluator(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    started = time.monotonic()
    time.sleep(settings.stub.sleep_seconds)

    questions = run.load_questions()
    unresolved = [q.id for q in questions.root if q.status != "resolved"]
    # Default-FAIL (invariant 2): pass only when nothing is unresolved.
    verdict = Verdict(
        passed=not unresolved,
        unmet_criteria=[f"question {qid} not resolved" for qid in unresolved],
        contradictions=[],
        new_questions=[],
        notes=f"STUB verdict for cycle {cycle}: "
        + ("all questions resolved" if not unresolved else f"{len(unresolved)} unresolved"),
    )
    run.write_verdict(cycle, verdict)
    run.log(
        f"evaluator (stub, cycle {cycle}): "
        + ("PASS" if verdict.passed else f"FAIL ({len(unresolved)} unresolved)")
    )
    return _result(settings, "evaluator", "evaluator", started, "pass" if verdict.passed else "fail", ledger, cycle)


def run_final_evaluator(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    """Stub terminal gate: passes iff nothing is unresolved (default-FAIL),
    writing a cycle-<n>-final.md verdict like the real two-tier gate."""
    started = time.monotonic()
    time.sleep(settings.stub.sleep_seconds)
    questions = run.load_questions()
    unresolved = [q.id for q in questions.root if q.status != "resolved"]
    verdict = Verdict(
        passed=not unresolved,
        unmet_criteria=[f"question {qid} not resolved" for qid in unresolved],
        contradictions=[],
        new_questions=[],
        notes=f"STUB FINAL verdict for cycle {cycle}",
    )
    run.write_verdict(cycle, verdict, final=True)
    run.log(
        f"final gate (stub, cycle {cycle}): " + ("PASS" if verdict.passed else "FAIL")
    )
    return _result(settings, "evaluator", "final_evaluator", started,
                   "final pass" if verdict.passed else "final fail", ledger, cycle)


def run_synthesizer(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    started = time.monotonic()
    time.sleep(settings.stub.sleep_seconds)

    sources = run.load_sources()
    findings = run.load_findings()

    # Citation pass (invariant 3): refuse to emit a claim whose source_id is
    # not in sources.json — loudly, even in the stub.
    for slug, (meta, _body) in findings.items():
        missing = [sid for sid in meta.source_ids if sid not in sources.root]
        if missing:
            raise SynthesisError(
                f"finding {slug!r} cites unknown source_ids {missing}; "
                "refusing to synthesize (invariant 3)"
            )

    reason = run.meta.finish_reason or "in-progress"
    partial = "" if reason == "conclusive" else (
        f"\n> **PARTIAL REPORT** — run ended early (reason: {reason}). "
        "Findings below are incomplete.\n"
    )
    lines = [
        f"# REPORT {_STUB_BANNER}",
        partial,
        f"**Question:** {run.meta.question}",
        "",
        "## Findings",
    ]
    if findings:
        for slug, (meta, _body) in sorted(findings.items()):
            cites = ", ".join(meta.source_ids)
            lines.append(
                f"- `{slug}` (question {meta.question_id}, "
                f"confidence {meta.confidence:.1f}) — sources: {cites}"
            )
    else:
        lines.append("- none — the run ended before any finding was produced")
    lines += ["", "## Limitations & decisions"]
    decisions = run.decisions()
    lines += [f"- {d}" for d in decisions] or ["- none logged"]
    run.write_text("REPORT.md", "\n".join(lines) + "\n")
    run.log(f"synthesizer (stub): wrote REPORT.md ({len(findings)} findings, reason={reason})")
    return _result(settings, "synthesizer", "synthesizer", started, f"report with {len(findings)} findings", ledger, cycle)
