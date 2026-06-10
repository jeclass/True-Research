"""Worker session (Sonnet driver + reader fan-out, CLAUDE.md §6 + Phase 3).

The worker investigates ONE question. It searches with WebSearch, but it
never reads pages itself: it calls the in-process MCP tool `read_source`,
and the ENGINE fetches the page and spawns a cheap reader session
(role `reader_subagent` — Haiku or a local model per config). The worker's
expensive context only ever sees compressed summaries; every read is
ledgered separately with its own endpoint attribution.

Endpoint note (docs/SDK_NOTES.md): in-session subagents inherit the parent's
process env, so endpoint mixing MUST happen via engine-spawned sessions —
which is exactly what the MCP handler does.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
from src.runspace import PLAN_FILE, Runspace
from src.sessions import common, reader
from src.sessions.base import (
    SessionError,
    SessionResult,
    WorkerError,
    run_role_session,
)
from src.settings import Settings
from src.state import FindingMeta, OpenQuestion

_ROLE = "worker"
_TOOLS = ["WebSearch", "Read", "Glob", "Grep"]
_READ_TOOL = "mcp__reader__read_source"

_SYSTEM_PROMPT = """\
You are a WORKER session of an autonomous research engine. You investigate
exactly ONE assigned open question per session — never any other question.

Method:
1. Use WebSearch to find candidate sources for the assigned question. Prefer
   primary/authoritative sources.
2. For each promising URL, call read_source(url, why). A separate reader
   agent fetches and digests the page and returns a compressed summary plus
   metadata (title, kind, credibility, notes). Issue several read_source
   calls in ONE message when you have several candidates — they run in
   parallel. Do NOT try to fetch pages yourself; read_source is your only
   window into page content.
3. Cross-check load-bearing claims across at least two independent sources
   when feasible. If a read fails or a page is not useful, move to the next
   candidate.
4. Produce your structured result (enforced JSON schema). No file writes —
   the engine persists your output.

Source rules:
- Register EVERY source your finding relies on, in `sources`, copying
  title/kind/credibility/notes from the read_source results.
- id format: ^src-[a-z0-9-]+$ — STRICTLY ASCII lowercase letters a-z, digits,
  hyphens. No accents or non-ASCII characters: transliterate them
  (Sundfør -> sundfor, Müller -> muller). Descriptive and unique, e.g.
  src-bmj-if-meta-2024. Reuse an existing registry id (listed in the task)
  only for the same URL. Use the identical id string in your [src-...]
  citations.

Finding rules (when outcome=resolved):
- finding.body_markdown: the finding as markdown. EVERY factual sentence ends
  with one or more citations like [src-id]. Cite only ids you register in
  `sources` or ids that already exist in the registry.
- finding.confidence: 0.0-1.0 — your confidence the finding answers the
  assigned question correctly.

outcome:
- "resolved"   — you answered the question. finding + sources required.
- "fragmented" — the question is too broad; return 2-4 child_questions
  (priority 1-5) that decompose it. No finding required.
- "blocked"    — you cannot make progress (reads failing, no sources,
  ambiguity); explain in blocked_reason. Do NOT fabricate.

progress_note: one line for the run log describing what you did."""


class ProposedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    url: str
    title: str
    kind: Literal["web", "paper", "page_capture"]
    credibility: int
    notes: str = ""


class ProposedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_markdown: str
    confidence: float


class ChildQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    priority: int


class WorkerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["resolved", "fragmented", "blocked"]
    finding: ProposedFinding | None = None
    sources: list[ProposedSource] = []
    child_questions: list[ChildQuestion] = []
    blocked_reason: str = ""
    progress_note: str


def _build_user_prompt(run: Runspace, target: OpenQuestion) -> str:
    plan = (run.root / PLAN_FILE).read_text(encoding="utf-8")
    questions = run.load_questions()
    sources = run.load_sources()
    return (
        f"# Assigned question\n{target.id} [priority {target.priority}]: {target.question}\n\n"
        f"# Research question (overall)\n{run.meta.question}\n\n"
        f"# Research plan\n{plan}\n\n"
        f"# All questions (context only — do not work on others)\n"
        f"{common.questions_digest(questions)}\n\n"
        f"# Existing source registry (reuse ids only for identical URLs)\n"
        f"{common.sources_digest(sources)}\n\n"
        f"# Existing findings (index)\n{common.findings_digest(run, full_bodies=False)}\n\n"
        f"# Recent run log\n{common.progress_tail(run)}\n"
    )


def _build_reader_mcp(
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    target: OpenQuestion,
    stats: dict[str, int],
):
    """In-process MCP server exposing read_source to the worker session.
    Lazy SDK import keeps stub-backend paths SDK-free."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool(
        "read_source",
        "Fetch ONE URL and get a compressed, citation-ready digest from a "
        "reader agent: returns TITLE/KIND/CREDIBILITY/NOTES plus a faithful "
        "summary of the page's facts relevant to the assigned question. Call "
        "it once per URL; batch several calls in one message to read in "
        "parallel.",
        {"url": str, "why": str},
    )
    async def read_source_tool(args: dict) -> dict:
        url = str(args.get("url", "")).strip()
        why = str(args.get("why", "")).strip()
        if not url:
            return {
                "content": [{"type": "text", "text": "READ FAILED: empty url"}],
                "is_error": True,
            }
        if stats["failures"] >= settings.reader.max_failures_per_session:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"READERS DISABLED: {stats['failures']} reads failed this "
                            "session (engine limit). Stop reading; report what you "
                            "have or outcome=blocked."
                        ),
                    }
                ],
                "is_error": True,
            }
        try:
            output, _spawn = await reader.read_source(
                run=run,
                settings=settings,
                ledger=ledger,
                cycle=cycle,
                url=url,
                question=target.question,
                why=why,
            )
        except SessionError as exc:
            stats["failures"] += 1
            return {
                "content": [{"type": "text", "text": f"READ FAILED: {exc}"}],
                "is_error": True,
            }
        stats["reads"] += 1
        if not output.useful:
            return {
                "content": [
                    {"type": "text", "text": f"PAGE NOT USEFUL: {output.notes}"}
                ]
            }
        text = (
            f"TITLE: {output.title}\n"
            f"KIND: {output.kind}\n"
            f"CREDIBILITY: {output.credibility}\n"
            f"NOTES: {output.notes}\n"
            f"URL: {url}\n"
            f"SUMMARY:\n{output.summary_markdown}"
        )
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server("reader", tools=[read_source_tool])


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    questions = run.load_questions()
    target = common.pick_target_question(questions)
    if target is None:
        raise WorkerError(
            "worker invoked with no open or in_progress questions — "
            "the driver should have exited conclusively before this"
        )
    target.status = "in_progress"
    run.save_questions(questions)

    stats = {"reads": 0, "failures": 0}
    reader_server = _build_reader_mcp(run, settings, ledger, cycle, target, stats)

    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="worker",
        role=_ROLE,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(run, target),
        tools=_TOOLS,
        output_model=WorkerOutput,
        mcp_servers={"reader": reader_server},
        extra_allowed_tools=[_READ_TOOL],
    )
    output: WorkerOutput = spawn.structured

    if stats["failures"] >= settings.reader.max_failures_per_session:
        run.log_decision(
            f"worker (cycle {cycle}): reader failure limit hit "
            f"({stats['failures']} failed reads) — reader backend/model may be "
            "unsuitable (§1 local-mode constraint)"
        )

    if output.outcome == "resolved":
        summary = _apply_resolved(run, target, output, cycle)
    elif output.outcome == "fragmented":
        summary = _apply_fragmented(run, target, output)
    else:
        summary = _apply_blocked(run, target, output)

    run.log(
        f"worker (cycle {cycle}): {output.progress_note} "
        f"[{stats['reads']} reads, {stats['failures']} failed]"
    )

    role_cfg = settings.roles[_ROLE]
    return SessionResult(
        session_type="worker",
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        input_tokens=spawn.input_tokens,
        output_tokens=spawn.output_tokens,
        cached_tokens=spawn.cached_tokens,
        usd=spawn.usd,
        wall_seconds=spawn.wall_seconds,
        summary=f"{summary} ({stats['reads']} reads, {spawn.num_turns} turns)",
    )


def _apply_resolved(
    run: Runspace, target: OpenQuestion, output: WorkerOutput, cycle: int
) -> str:
    if output.finding is None:
        raise WorkerError(f"{target.id}: outcome=resolved but no finding returned")
    if not 0.0 <= output.finding.confidence <= 1.0:
        raise WorkerError(
            f"{target.id}: confidence {output.finding.confidence} outside 0-1"
        )

    registry = common.merge_sources(
        run, [s.model_dump() for s in output.sources], WorkerError
    )

    body = output.finding.body_markdown.strip()
    cited = common.CITATION_RE.findall(body)
    if not cited:
        raise WorkerError(
            f"{target.id}: finding contains no [src-...] citations — "
            "claims must be traceable (invariant 3)"
        )
    unknown = sorted({c for c in cited if c not in registry.root})
    if unknown:
        raise WorkerError(
            f"{target.id}: finding cites unregistered sources {unknown} (invariant 3)"
        )

    slug = f"{target.id}-c{cycle:02d}"
    run.write_finding(
        slug,
        FindingMeta(
            question_id=target.id,
            source_ids=sorted(set(cited)),
            confidence=output.finding.confidence,
        ),
        body,
    )

    questions = run.load_questions()
    fresh_target = questions.get(target.id)
    fresh_target.status = "resolved"
    fresh_target.resolved_by_finding = slug
    run.save_questions(questions)
    return f"resolved {target.id} -> findings/{slug}.md ({len(set(cited))} sources)"


def _apply_fragmented(run: Runspace, target: OpenQuestion, output: WorkerOutput) -> str:
    if not output.child_questions:
        raise WorkerError(f"{target.id}: outcome=fragmented but no child_questions")
    questions = run.load_questions()
    child_ids = []
    for child in output.child_questions:
        common.check_priority(child.priority, WorkerError, f"child of {target.id}")
        child_id = common.next_question_id(questions)
        questions.root.append(
            OpenQuestion(
                id=child_id,
                question=child.question,
                priority=child.priority,
                parent_id=target.id,
                created_by="worker",
            )
        )
        child_ids.append(child_id)
    fresh_target = questions.get(target.id)
    fresh_target.status = "resolved"  # decomposed; the children carry it forward
    run.save_questions(questions)
    run.log_decision(
        f"worker fragmented {target.id} into {', '.join(child_ids)} — "
        "parent marked resolved without a finding"
    )
    return f"fragmented {target.id} -> {', '.join(child_ids)}"


def _apply_blocked(run: Runspace, target: OpenQuestion, output: WorkerOutput) -> str:
    reason = output.blocked_reason.strip() or "no reason given"
    questions = run.load_questions()
    fresh_target = questions.get(target.id)
    fresh_target.status = "open"  # stays open; stall guard ends repeat blocks
    run.save_questions(questions)
    run.log_decision(f"worker BLOCKED on {target.id}: {reason}")
    return f"blocked on {target.id}"
