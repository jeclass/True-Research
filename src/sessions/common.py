"""Helpers shared by the real session modules: question-id allocation,
priority validation, source-registry merging, and compact state digests for
prompts. All state mutations stay in deterministic engine code — models only
return structured proposals."""

from __future__ import annotations

import re

from src.runspace import Runspace
from src.sessions.base import SessionError
from src.state import OpenQuestion, QuestionList, SourceRecord, SourceRegistry, utcnow

SOURCE_ID_RE = re.compile(r"^src-[a-z0-9][a-z0-9-]{0,60}$")
CITATION_RE = re.compile(r"\[(src-[a-z0-9][a-z0-9-]{0,60})\]")
_QID_RE = re.compile(r"^q-(\d+)$")

PRIORITY_MIN, PRIORITY_MAX = 1, 5


def check_priority(priority: int, error_cls: type[SessionError], context: str) -> int:
    if not PRIORITY_MIN <= priority <= PRIORITY_MAX:
        raise error_cls(
            f"{context}: priority {priority} outside {PRIORITY_MIN}-{PRIORITY_MAX}"
        )
    return priority


def next_question_id(questions: QuestionList) -> str:
    highest = 0
    for q in questions.root:
        match = _QID_RE.match(q.id)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"q-{highest + 1:03d}"


def pick_target_question(questions: QuestionList) -> OpenQuestion | None:
    """Orphaned in_progress questions first, then highest-priority open.

    An in_progress question at cycle start can only be an orphan — every
    worker exit path (resolved, fragmented, blocked) moves the status, so
    in_progress survives only a crash/error. Without this precedence an
    orphan starves until all open questions are exhausted (observed live in
    the Phase 2 smoke run)."""
    candidates = questions.in_progress_items() or questions.open_items()
    if not candidates:
        return None
    return sorted(candidates, key=lambda q: (-q.priority, q.id))[0]


def merge_sources(
    run: Runspace,
    proposed: list[dict],
    error_cls: type[SessionError],
) -> SourceRegistry:
    """Merge model-proposed sources into sources.json. Same id + same URL is a
    no-op; same id + different URL is an error (no silent overwrite)."""
    registry = run.load_sources()
    for item in proposed:
        source_id = item["id"]
        if not SOURCE_ID_RE.match(source_id):
            raise error_cls(
                f"proposed source id {source_id!r} does not match {SOURCE_ID_RE.pattern}"
            )
        credibility = int(item["credibility"])
        if not 0 <= credibility <= 100:
            raise error_cls(f"source {source_id}: credibility {credibility} outside 0-100")
        record = SourceRecord(
            url=item["url"],
            title=item["title"],
            kind=item["kind"],
            credibility=credibility,
            retrieved_at=utcnow(),
            notes=item.get("notes", ""),
        )
        existing = registry.root.get(source_id)
        if existing is not None and existing.url != record.url:
            raise error_cls(
                f"source id collision: {source_id} already registered for "
                f"{existing.url}, proposal points at {record.url}"
            )
        if existing is None:
            registry.root[source_id] = record
    run.save_sources(registry)
    return registry


def questions_digest(questions: QuestionList) -> str:
    if not questions.root:
        return "(none yet)"
    lines = []
    for q in questions.root:
        suffix = f" -> findings/{q.resolved_by_finding}.md" if q.resolved_by_finding else ""
        lines.append(f"- {q.id} [p{q.priority}] ({q.status}{suffix}): {q.question}")
    return "\n".join(lines)


def sources_digest(registry: SourceRegistry) -> str:
    if not registry.root:
        return "(none registered yet)"
    return "\n".join(
        f"- {sid}: {rec.title} ({rec.kind}, credibility {rec.credibility}) {rec.url}"
        for sid, rec in sorted(registry.root.items())
    )


def findings_digest(run: Runspace, full_bodies: bool) -> str:
    """Compact index for the worker; full bodies for evaluator/synthesizer
    (Phase 2 runs are bounded; Phase 3 adds fan-out/compaction)."""
    findings = run.load_findings()
    if not findings:
        return "(no findings yet)"
    parts = []
    for slug, (meta, body) in sorted(findings.items()):
        head = (
            f"### findings/{slug}.md (question {meta.question_id}, "
            f"confidence {meta.confidence:.2f}, sources: {', '.join(meta.source_ids)})"
        )
        parts.append(f"{head}\n{body.strip()}" if full_bodies else head)
    return "\n\n".join(parts)


def progress_tail(run: Runspace, max_lines: int = 40) -> str:
    text = (run.root / "PROGRESS.md").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    return "\n".join(lines[-max_lines:]) or "(empty)"
