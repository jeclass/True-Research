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
from src.profiles import WorkerToolContext, get_profile
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
_READ_TOOL = "mcp__reader__read_source"

_SYSTEM_PROMPT = """\
You are a WORKER session of an autonomous research engine. You investigate
exactly ONE assigned open question per session — never any other question.

Method:
1. Use the available search tools to find candidate sources for the assigned
   question. Prefer primary/authoritative sources.
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
- excerpts: if a read_source result included a KEY QUOTES block, copy those
  quotes CHARACTER-FOR-CHARACTER into the source's `excerpts` array — they
  become the report's checkable citation anchor. Never write your own quote
  here; only copy what read_source gave you, or leave it empty.
- READ-GATE (hard rule, enforced by the engine): a source may be registered
  ONLY under the exact URL that returned a successful read_source digest THIS
  session (or an id already in the registry). A source you merely found via
  search does NOT qualify. Never substitute a canonical/DOI/abstract URL for
  the URL you actually read — if you read a mirror (e.g. PMC full text),
  register the mirror URL and put the canonical reference in `notes`.
- id format: ^src-[a-z0-9-]+$ — STRICTLY ASCII lowercase letters a-z, digits,
  hyphens. No accents or non-ASCII characters: transliterate them
  (Sundfør -> sundfor, Müller -> muller). Descriptive and unique, e.g.
  src-bmj-if-meta-2024. Reuse an existing registry id (listed in the task)
  only for the same URL. Use the identical id string in your [src-...]
  citations.
- EXACT-MATCH rule: every [src-...] citation in body_markdown must be a
  character-for-character copy of an id in your `sources` array (or the
  registry). Before finishing, verify each citation string-matches a
  registered id — a mismatched or abbreviated id fails the whole finding.

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
    # Span-level citation anchors (roadmap): copied verbatim from read_source's
    # KEY QUOTES block — see the "Source rules" guidance above. The engine does
    # NOT re-verify these against the page text here (the reader already did, in
    # reader.read_source); a model that ignores the "copy, don't invent" guidance
    # could in principle smuggle a paraphrase through this path. Pipeline mode
    # (the default backend) is engine-verified end-to-end and is the trustworthy
    # source of this field; treat agentic-mode excerpts as best-effort.
    excerpts: list[str] = []


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


def build_system_prompt(profile) -> str:
    """Stable per-run prompt: engine method + the profile's domain guidance."""
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Domain guidance (profile: {profile.name})\n"
        + profile.worker_guidance()
    )


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


def _format_read_result(output: reader.ReaderOutput, url: str) -> str:
    """The read_source MCP tool's result text — what the agentic worker sees
    after a successful read. A pure function (no SDK dependency) so it unit-tests
    directly. The KEY QUOTES block only appears when the reader proposed
    engine-verified quotes (roadmap: span-level citation anchors) — the worker is
    told to copy them verbatim into ProposedSource.excerpts, never invent its own."""
    quotes_block = (
        "\nKEY QUOTES (verbatim — copy character-for-character into this "
        "source's `excerpts` if you cite it):\n"
        + "\n".join(f'- "{q}"' for q in output.key_quotes)
        if output.key_quotes
        else ""
    )
    return (
        f"TITLE: {output.title}\n"
        f"KIND: {output.kind}\n"
        f"CREDIBILITY: {output.credibility}\n"
        f"NOTES: {output.notes}\n"
        f"URL: {url}\n"
        f"SUMMARY:\n{output.summary_markdown}"
        f"{quotes_block}"
    )


def _build_reader_mcp(
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    target: OpenQuestion,
    stats: dict[str, int],
    read_urls: set[str],
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
        # Only useful reads qualify a URL for citation (the engine's read-gate).
        read_urls.add(common.normalize_url(url))
        return {"content": [{"type": "text", "text": _format_read_result(output, url)}]}

    return create_sdk_mcp_server("reader", tools=[read_source_tool])


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    questions = run.load_questions()
    wp = settings.worker_pipeline
    if wp.enabled and wp.parallel_questions > 1:
        # Parallel fan-out (roadmap): investigate up to N questions concurrently.
        # Pipeline mode only — the agentic path below is a sync open loop.
        return _run_parallel(run, settings, cycle, ledger, questions, wp.parallel_questions)

    target = common.pick_target_question(questions)
    if target is None:
        raise WorkerError(
            "worker invoked with no open or in_progress questions — "
            "the driver should have exited conclusively before this"
        )
    target.status = "in_progress"
    run.save_questions(questions)

    if settings.worker_pipeline.enabled:
        # Pipeline-worker mode (operator decision 2026-06-10): single-shot
        # local sessions + engine orchestration; the agentic loop below is
        # the cloud-worker alternative (worker_pipeline.enabled: false).
        from src.sessions import pipeline

        profile = get_profile(run.meta.profile)
        return pipeline.run_pipeline(run, settings, cycle, ledger, target, profile)

    stats = {"reads": 0, "failures": 0}
    read_urls: set[str] = set()
    reader_server = _build_reader_mcp(
        run, settings, ledger, cycle, target, stats, read_urls
    )

    # Profile = domain tool set + worker guidance (§7). The reader is engine-
    # owned and attached for every profile.
    profile = get_profile(run.meta.profile)
    ctx = WorkerToolContext(
        run=run, settings=settings, ledger=ledger, cycle=cycle,
        target=target, stats=stats, read_urls=read_urls,
    )
    toolset = profile.worker_toolset(ctx)

    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="worker",
        role=_ROLE,
        system_prompt=build_system_prompt(profile),
        user_prompt=_build_user_prompt(run, target),
        tools=toolset.builtin,
        output_model=WorkerOutput,
        mcp_servers={"reader": reader_server, **toolset.mcp_servers},
        extra_allowed_tools=[_READ_TOOL] + toolset.extra_allowed,
    )
    output: WorkerOutput = spawn.structured

    if stats["failures"] >= settings.reader.max_failures_per_session:
        run.log_decision(
            f"worker (cycle {cycle}): reader failure limit hit "
            f"({stats['failures']} failed reads) — reader backend/model may be "
            "unsuitable (§1 local-mode constraint)"
        )

    summary = _apply_outcome(run, settings, target, output, cycle, read_urls)

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


def _run_parallel(
    run: Runspace,
    settings: Settings,
    cycle: int,
    ledger: Ledger,
    questions,
    k: int,
) -> SessionResult:
    """Investigate up to k distinct questions CONCURRENTLY in one event loop
    (roadmap: parallel worker fan-out). Correctness rests on the pipeline's apply
    sections being await-free, so cooperative scheduling serializes the shared-
    state writes for free (see pipeline.run_pipeline_batch). The driver loop is
    otherwise unchanged — one evaluator pass still judges the merged result."""
    from src.sessions import pipeline

    targets = common.pick_target_questions(questions, k)
    if not targets:
        raise WorkerError(
            "worker invoked with no open or in_progress questions — "
            "the driver should have exited conclusively before this"
        )
    for t in targets:
        t.status = "in_progress"
    run.save_questions(questions)
    run.log(
        f"worker (cycle {cycle}): parallel fan-out over {len(targets)} "
        f"questions ({', '.join(t.id for t in targets)})"
    )

    profile = get_profile(run.meta.profile)
    results = pipeline.run_pipeline_batch(run, settings, cycle, ledger, targets, profile)

    ok: list[SessionResult] = []
    errored: list[str] = []
    for t, res in zip(targets, results):
        if isinstance(res, BaseException):
            # One question's failure must not lose the others' work. Leave it
            # in_progress: the orphan picker re-claims it next cycle (invariant 8).
            run.log_decision(
                f"parallel worker for {t.id} errored ({res!r}); left in_progress "
                "for the orphan picker to retry next cycle"
            )
            errored.append(t.id)
        else:
            ok.append(res)

    role_cfg = settings.roles[_ROLE]
    summary = f"parallel: {len(ok)}/{len(targets)} questions investigated"
    if errored:
        summary += f", {len(errored)} errored ({', '.join(errored)})"
    return SessionResult(
        session_type="worker",
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        # Per-session spend is already in the ledger (each inner session records
        # itself); these sums are display-only. wall_seconds is the MAX, not the
        # sum — the whole point is they overlapped.
        input_tokens=sum(r.input_tokens for r in ok),
        output_tokens=sum(r.output_tokens for r in ok),
        cached_tokens=sum(r.cached_tokens for r in ok),
        usd=sum(r.usd for r in ok),
        wall_seconds=max((r.wall_seconds for r in ok), default=0.0),
        summary=summary,
    )


def _apply_outcome(
    run: Runspace,
    settings: Settings,
    target: OpenQuestion,
    output: WorkerOutput,
    cycle: int,
    read_urls: set[str],
) -> str:
    """Dispatch the worker outcome, degrading any malformed-output WorkerError
    (resolved with no finding / confidence out of range / uncited or
    unregistered-source finding / bad child priority) to a SOFT BLOCK instead of
    crashing a multi-cycle run that already has findings on disk. The bad output
    is rejected (no finding is written on a failing path), the question stays open
    for a clean retry, and the blocked-count backstop retires it if the worker
    keeps failing — so invariant 3 (traceability) still holds. Surfaced to
    DECISIONS (invariant 8)."""
    try:
        if output.outcome == "resolved":
            return _apply_resolved(run, settings, target, output, cycle, read_urls)
        if output.outcome == "fragmented":
            return _apply_fragmented(run, settings, target, output)
        return _apply_blocked(run, target, output)
    except WorkerError as exc:
        run.log_decision(
            f"worker output for {target.id} rejected ({exc}); degraded to a soft "
            "block rather than crashing the run"
        )
        return _apply_blocked(
            run,
            target,
            output.model_copy(update={"blocked_reason": f"rejected worker output: {exc}"}),
        )


def _apply_resolved(
    run: Runspace,
    settings: Settings,
    target: OpenQuestion,
    output: WorkerOutput,
    cycle: int,
    read_urls: set[str],
) -> str:
    if output.finding is None:
        raise WorkerError(f"{target.id}: outcome=resolved but no finding returned")
    if not 0.0 <= output.finding.confidence <= 1.0:
        raise WorkerError(
            f"{target.id}: confidence {output.finding.confidence} outside 0-1"
        )

    require_reads = settings.reader.require_reads
    if not require_reads:
        run.log_decision(
            f"{target.id}: reader.require_reads=false — finding may rest on "
            "sources not fetched via read_source (no-egress/degraded mode)"
        )
    registry = common.merge_sources(
        run,
        [s.model_dump() for s in output.sources],
        WorkerError,
        read_urls=read_urls,
        require_reads=require_reads,
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


def _apply_fragmented(
    run: Runspace, settings: Settings, target: OpenQuestion, output: WorkerOutput
) -> str:
    if not output.child_questions:
        # The worker said "this is too broad, fragment it" but gave no children —
        # an incoherent decomposition (observed 2026-06-24 from DeepSeek Flash mid
        # multi-cycle run). A single malformed worker turn must NOT crash the run
        # (it had findings + state on disk). Degrade to a soft block: the question
        # stays open so the worker can fragment it correctly on a later cycle, and
        # if it never does, the blocked-count backstop retires it. Surfaced to
        # DECISIONS per invariant 8.
        run.log_decision(
            f"worker returned outcome=fragmented for {target.id} with no "
            "child_questions (malformed decomposition); degraded to a soft block "
            "rather than crashing the run"
        )
        degraded = output.model_copy(
            update={
                "blocked_reason": "worker said 'fragmented' but provided no "
                "child_questions (malformed decomposition)"
            }
        )
        return _apply_blocked(run, target, degraded)
    questions = run.load_questions()
    tree = settings.question_tree
    child_depth = target.depth + 1

    # Bound the question tree (docs/COMPREHENSIVE_RESEARCH_SPEC item 2). When a
    # fragment would breach the depth limit or the total-question cap, refuse
    # it: the question becomes a LEAF (resolved, no finding) and the choice is
    # surfaced to DECISIONS (invariant 8). Permissive defaults mean normal runs
    # never hit these — they bound deep/comprehensive runs from runaway growth.
    def _cap_as_leaf(reason: str) -> str:
        fresh = questions.get(target.id)
        fresh.status = "resolved"
        run.save_questions(questions)
        run.log_decision(f"fragmentation of {target.id} REFUSED: {reason}")
        return f"capped {target.id}"

    if child_depth > tree.max_depth:
        return _cap_as_leaf(
            f"question-tree depth {tree.max_depth} reached; treated as a leaf "
            "(no finding)"
        )
    if len(questions.root) + len(output.child_questions) > tree.max_questions:
        return _cap_as_leaf(
            f"question cap {tree.max_questions} reached "
            f"({len(questions.root)} existing); treated as a leaf (no finding)"
        )

    child_ids = []
    for child in output.child_questions:
        common.check_priority(child.priority, WorkerError, f"child of {target.id}")
        dup = common.duplicate_question_id(child.question, questions)
        if dup is not None:
            run.log_decision(
                f"worker fragmenting {target.id}: child near-duplicates {dup}; dropped"
            )
            continue
        child_id = common.next_question_id(questions)
        questions.root.append(
            OpenQuestion(
                id=child_id,
                question=child.question,
                priority=child.priority,
                parent_id=target.id,
                created_by="worker",
                depth=child_depth,
                track=target.track,  # children stay on the parent's lens track
            )
        )
        child_ids.append(child_id)
    fresh_target = questions.get(target.id)
    fresh_target.status = "resolved"  # decomposed; the children carry it forward
    run.save_questions(questions)
    run.log_decision(
        f"worker fragmented {target.id} (depth {target.depth}->{child_depth}) "
        f"into {', '.join(child_ids)} — parent resolved without a finding"
    )
    return f"fragmented {target.id} -> {', '.join(child_ids)}"


def _apply_blocked(
    run: Runspace, target: OpenQuestion, output: WorkerOutput, hard_block: bool = False
) -> str:
    reason = output.blocked_reason.strip() or "no reason given"
    questions = run.load_questions()
    fresh_target = questions.get(target.id)
    fresh_target.status = "open"  # stays open; stall guard ends repeat blocks
    # A HARD block — the engine read real pages this cycle and the reader
    # judged NONE useful — is strong evidence the facet is unanswerable on the
    # open web, so it counts double: one hard block reaches the evaluator's
    # exhausted-scope close threshold (2), letting the run converge instead of
    # grinding a dead facet into a stall (observed round 17, 2026-06-11). A
    # SOFT block (transient fetch failures only) still needs two.
    fresh_target.blocked_count += 2 if hard_block else 1
    run.save_questions(questions)
    kind = "HARD" if hard_block else "soft"
    run.log_decision(
        f"worker BLOCKED on {target.id} "
        f"({kind}, count={fresh_target.blocked_count}): {reason}"
    )
    return f"blocked on {target.id}"
