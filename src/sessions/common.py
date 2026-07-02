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


def normalize_url(url: str) -> str:
    """Loose canonical form for matching a cited source URL against the set of
    URLs actually read this run: lowercase scheme+host, strip trailing slash
    and fragment. Deliberately not a full URL canonicalizer — just enough to
    forgive trailing-slash / case drift between the read call and the source
    record."""
    raw = url.strip()
    raw = raw.split("#", 1)[0]
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if "/" in rest:
            host, path = rest.split("/", 1)
            raw = f"{scheme.lower()}://{host.lower()}/{path}"
        else:
            raw = f"{scheme.lower()}://{rest.lower()}"
    return raw.rstrip("/")

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


# Conservative — catches verbatim / near-verbatim re-emissions without
# dropping meaningfully-different questions (e.g. same facet, different
# population). The bulk of observed duplicates are exact repeats (ratio 1.0).
_DUP_THRESHOLD = 0.90


def _normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def duplicate_question_id(text: str, questions: QuestionList) -> str | None:
    """Id of an existing question that `text` substantially duplicates
    (normalized exact match or difflib ratio >= _DUP_THRESHOLD), else None.

    Guards against the local evaluator re-emitting existing questions as
    'new' ones every cycle, which pollutes the queue and blocks convergence
    (observed comprehensive run 2026-06-15: 22 of 35 questions were near-
    verbatim duplicates of the 13 seeds). Compares against ALL questions —
    re-asking a resolved question is as wasteful as re-asking an open one."""
    from difflib import SequenceMatcher

    norm = _normalize_question(text)
    if not norm:
        return None
    for q in questions.root:
        existing = _normalize_question(q.question)
        if norm == existing or SequenceMatcher(None, norm, existing).ratio() >= _DUP_THRESHOLD:
            return q.id
    return None


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


def pick_target_questions(questions: QuestionList, k: int) -> list[OpenQuestion]:
    """Up to k DISTINCT targets for a parallel-fan-out cycle (roadmap): orphaned
    in_progress questions first (same precedence as the single picker), then the
    highest-priority open ones, in deterministic order. k<=1 collapses to the same
    single target pick_target_question would return, so parallel mode is a strict
    superset of the sequential path."""
    ordered = (
        sorted(questions.in_progress_items(), key=lambda q: (-q.priority, q.id))
        + sorted(questions.open_items(), key=lambda q: (-q.priority, q.id))
    )
    return ordered[: max(1, k)]


def merge_sources(
    run: Runspace,
    proposed: list[dict],
    error_cls: type[SessionError],
    read_urls: set[str] | None = None,
    require_reads: bool = False,
) -> SourceRegistry:
    """Merge model-proposed sources into sources.json. Same id + same URL is a
    no-op; same id + different URL is an error (no silent overwrite).

    Read-gating (ultimate-depth, invariant 3): when require_reads is true, a
    NEW source may be registered only if its URL was actually read this run
    (present in read_urls). Sources already in the registry were read in a
    prior cycle and may be reused. A source the worker never read cannot
    become a citation — WebSearch is discovery only, reads are evidence."""
    read_urls = read_urls or set()
    registry = run.load_sources()
    existing_urls = {normalize_url(rec.url) for rec in registry.root.values()}
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
            # Span-level citation anchors (roadmap): absent for older callers /
            # an agentic worker that proposed none — SourceRecord defaults to [].
            excerpts=item.get("excerpts") or [],
        )
        existing = registry.root.get(source_id)
        # Normalized comparison (final review): two parallel questions reading
        # normalized-equal URL variants ('…/page' vs '…/page/') must be the
        # same-source no-op, not a spurious collision that discards the losing
        # question's whole cycle as a WorkerError.
        if existing is not None and normalize_url(existing.url) != normalize_url(record.url):
            raise error_cls(
                f"source id collision: {source_id} already registered for "
                f"{existing.url}, proposal points at {record.url}"
            )
        if existing is None:
            norm = normalize_url(record.url)
            if require_reads and norm not in read_urls and norm not in existing_urls:
                raise error_cls(
                    f"source {source_id} ({record.url}) was never read via "
                    "read_source this run — a source can only be cited if it was "
                    "fetched and judged useful (invariant 3). WebSearch is for "
                    "discovery; call read_source on a URL before citing it."
                )
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


def _source_line(sid, rec) -> str:
    return f"- {sid}: {rec.title} ({rec.kind}, credibility {rec.credibility}) {rec.url}"


def sources_digest(registry: SourceRegistry, max_sources: int | None = None) -> str:
    """Full registry by default. max_sources caps the list to the most-credible
    N (with a count of what was omitted) — used by the per-cycle evaluator so a
    large registry can't overflow its local context (root-cause fix
    2026-06-15). The evaluator judges source quality, so the best are kept."""
    if not registry.root:
        return "(none registered yet)"
    items = sorted(registry.root.items())
    if max_sources is not None and len(items) > max_sources:
        top = sorted(items, key=lambda kv: -kv[1].credibility)[:max_sources]
        lines = [_source_line(sid, rec) for sid, rec in sorted(top)]
        lines.append(
            f"- …and {len(items) - max_sources} more lower-credibility "
            "sources (omitted to fit context)"
        )
        return "\n".join(lines)
    return "\n".join(_source_line(sid, rec) for sid, rec in items)


def findings_digest(
    run: Runspace,
    full_bodies: bool,
    only_tracks: set[str] | None = None,
    max_total_chars: int | None = None,
) -> str:
    """Compact index for the worker; full bodies for evaluator/synthesizer.
    only_tracks filters by finding track — None (default) includes every track
    (byte-identical to pre-lens behavior); the synthesizer passes {"factual"}.

    max_total_chars caps the TOTAL body text by distributing the budget across
    findings (per-finding excerpt = budget // count), so the digest cannot
    overflow a limited context regardless of how many findings accrue
    (root-cause fix 2026-06-15: the per-cycle local evaluator hit ~30.7k tokens
    at 13 full findings and 5xx-ed). Headers (question id, confidence,
    verification, source ids) are always shown in full — the evaluator's core
    job is judging resolution + traceability, which the headers carry. None =>
    no cap (the Opus final gate and synthesizer keep full text)."""
    findings = run.load_findings()
    if only_tracks is not None:
        findings = {
            slug: pair for slug, pair in findings.items() if pair[0].track in only_tracks
        }
    if not findings:
        return "(no findings yet)"
    per_finding = (
        max_total_chars // len(findings)
        if full_bodies and max_total_chars is not None
        else None
    )
    parts = []
    for slug, (meta, body) in sorted(findings.items()):
        ver = (
            ""
            if meta.verification_status == "unverified"
            else f", VERIFICATION: {meta.verification_status.upper()}"
        )
        head = (
            f"### findings/{slug}.md (question {meta.question_id}, "
            f"confidence {meta.confidence:.2f}{ver}, "
            f"sources: {', '.join(meta.source_ids)})"
        )
        if not full_bodies:
            parts.append(head)
            continue
        text = body.strip()
        if per_finding is not None and per_finding <= 0:
            # Degenerate budget (findings outnumber max_total_chars): the
            # head/tail split below would compute tail_n == 0, and text[-0:]
            # returns the ENTIRE body — silently defeating the cap (final
            # review). Degrade to headers-only; the headers carry the
            # evaluator's core job (resolution + traceability).
            parts.append(f"{head}\n…[body elided to fit evaluator context]…")
            continue
        if per_finding is not None and len(text) > per_finding:
            # HEAD + TAIL, not head-only (mirrors reader.py's 2026-06-29 fix,
            # audit #4). Plain text[:per_finding] dropped the back of every long
            # finding, so a late claim or citation in its tail became invisible to
            # the default-FAIL evaluator — which then judged the question
            # unresolved / the claim untraceable on content it never saw. Keep the
            # head AND the tail, eliding only the middle, with a marker so the
            # evaluator treats the gap as UNKNOWN rather than absence.
            head_n = int(per_finding * 0.75)
            tail_n = per_finding - head_n
            elided = len(text) - per_finding
            text = (
                text[:head_n].rstrip()
                + f"\n…[{elided} chars elided from the MIDDLE to fit evaluator "
                "context; head+tail kept — treat anything missing here as UNKNOWN, "
                "not absent]…\n"
                + text[-tail_n:].lstrip()
            )
        parts.append(f"{head}\n{text}")
    return "\n\n".join(parts)


def progress_tail(run: Runspace, max_lines: int = 40) -> str:
    text = (run.root / "PROGRESS.md").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith("- ")]
    return "\n".join(lines[-max_lines:]) or "(empty)"
