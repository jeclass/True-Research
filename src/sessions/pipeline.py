"""Pipeline-worker mode (docs/PIPELINE_WORKER_SPEC.md, operator-approved).

Replaces the open-loop agentic worker with single-shot local calls plus
engine orchestration — the pattern local models executed flawlessly on the
operator's hardware while agentic loops failed three different ways:

  query-gen (1 local session) -> engine search (profile providers) ->
  rule-based URL selection -> reader fan-out (existing) ->
  ENGINE-built sources -> compose (1 local session) -> existing apply gates.

The model never types a URL and never invents a source id — invariant 3's
empirical failure classes (cite-without-read, id typos, id collisions) are
structurally impossible. The agentic path remains when
worker_pipeline.enabled is false.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, model_validator

from src.errors import ConfigError
from src.ledger import Ledger
from src.profiles import Profile
from src.runspace import PLAN_FILE, Runspace
from src.sessions import common, reader, untrusted
from src.sessions.base import (
    SessionError,
    SessionResult,
    WorkerError,
    parse_prompted_json,
    run_role_session_with_fallback_async,
)
from src.sessions.worker import (
    ChildQuestion,
    ProposedFinding,
    _apply_blocked,
    _apply_fragmented,
)
from src.settings import Settings
from src.state import FindingMeta, OpenQuestion, SourceRegistry

_ROLE = "worker"

# Optional compose role (COMPREHENSIVE_RESEARCH_SPEC §1): when configured in
# config.yaml `roles:`, the ONE one-shot compose call per resolved question
# routes there (a stronger synthesis model); query-gen and readers stay on
# the worker posture. Absent => compose uses _ROLE — the certified behavior.
_COMPOSE_ROLE = "compose"

_QUERY_GEN_SYSTEM = """\
You generate web-search queries for ONE research question. You have no tools
and make exactly one response.

Rules:
- Queries must be directly usable in a search engine: specific, varied
  angles, no boolean operator soup.
- Cover the question's distinct facets; avoid near-duplicate phrasings.
- Where the domain guidance names source types (e.g. meta-analyses, primary
  trials, guidelines), include queries targeted at finding exactly those.
- notes: one line on your query strategy.
Respond ONLY via the enforced JSON schema."""

_COMPOSE_SYSTEM = """\
You compose ONE research finding from reader summaries. You have no tools and
make exactly one response. The engine fetched and digested the sources; your
job is faithful synthesis — nothing in your finding may go beyond what the
summaries support.

Citation rules (engine-enforced):
- You are given a MENU of valid source ids. Every factual sentence in
  body_markdown ends with one or more citations like [src-id], copied
  CHARACTER-FOR-CHARACTER from the menu. Ids not on the menu fail the whole
  finding. Do not cite sources whose summary you did not use.
- Cross-check: where summaries disagree, say so and cite both sides.

outcome:
- "resolved"   — the summaries answer the assigned question. finding required.
- "fragmented" — the question is too broad even with this evidence; return
  2-4 child_questions (priority 1-5). No finding.
- "blocked"    — the summaries cannot support an answer; say why in
  blocked_reason. Do NOT fabricate.

# Response format (MANDATORY — two parts)
Part 1: a SMALL json object (in a ```json fence) with EXACTLY these fields:
```json
{"outcome": "resolved", "confidence": 0.85, "child_questions": [],
 "blocked_reason": "", "progress_note": "one line for the run log"}
```
confidence: 0.0-1.0, required when outcome is "resolved".
child_questions entries: {"question": "...", "priority": 1-5}.

Part 2 (ONLY when outcome is "resolved"): on its own line write exactly
---FINDING---
then the finding body as plain markdown — NOT inside JSON, no escaping.
Every factual sentence ends with [src-id] citations from the menu.
When outcome is "fragmented" or "blocked", stop after Part 1."""

# Reader summaries derive from untrusted web pages — append the injection-defense
# clause so a summary that carried injection text forward can't redirect compose.
_COMPOSE_SYSTEM = _COMPOSE_SYSTEM + "\n\n" + untrusted.INJECTION_DEFENSE_CLAUSE


class QueryGenOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str]
    notes: str


class ComposeHeader(BaseModel):
    """Part 1 of the two-part compose format: small JSON, no long strings.
    The finding body travels OUTSIDE the JSON (after ---FINDING---) because
    multi-paragraph markdown inside a JSON string is the dominant local-model
    parse-failure cause (observed: 3 consecutive escape/truncation failures
    on one compose, smoke4 2026-06-10)."""

    model_config = ConfigDict(extra="forbid")
    outcome: Literal["resolved", "fragmented", "blocked"]
    confidence: float | None = None
    child_questions: list[ChildQuestion] = []
    blocked_reason: str = ""
    # Optional: models reasonably treat blocked_reason as the note and omit
    # this (observed smoke9 p2 2026-06-10) — parse_compose_output derives it.
    progress_note: str = ""


_FINDING_SENTINEL = "---FINDING---"


def parse_compose_output(
    text: str, valid_ids: set[str] | None = None
) -> "ComposeOutput":
    """Split the two-part compose reply and build a validated ComposeOutput.
    Raises ValueError on any defect so the single-shot retry net rerolls —
    including citations outside `valid_ids` (hallucinated source ids are a
    bad roll like any other; observed smoke10 2026-06-10: a ceramic-kiln id
    invented inside an EV-battery finding). The apply-phase registry check
    remains as the final defense."""
    head, sep, body = text.partition(_FINDING_SENTINEL)
    header = parse_prompted_json(head, ComposeHeader)
    if not header.progress_note.strip():
        derived = {
            "resolved": "composed finding from reader summaries",
            "fragmented": f"fragmented into {len(header.child_questions)} child questions",
            "blocked": f"blocked: {header.blocked_reason.strip() or 'no reason given'}",
        }[header.outcome]
        header = header.model_copy(update={"progress_note": derived})
    body = body.strip()
    finding = None
    if header.outcome == "resolved":
        if not body:
            raise ValueError(
                "prompted-JSON parse failed: outcome=resolved but no "
                f"{_FINDING_SENTINEL} body section"
            )
        if header.confidence is None:
            raise ValueError(
                "prompted-JSON parse failed: outcome=resolved requires confidence"
            )
        finding = ProposedFinding(
            body_markdown=body, confidence=header.confidence
        )
        if valid_ids is not None:
            cited = set(common.CITATION_RE.findall(body))
            off_menu = sorted(cited - valid_ids)
            if off_menu:
                raise ValueError(
                    f"prompted-JSON parse failed: finding cites ids outside "
                    f"the menu {off_menu}"
                )
    return ComposeOutput(
        outcome=header.outcome,
        finding=finding,
        child_questions=header.child_questions,
        blocked_reason=header.blocked_reason,
        progress_note=header.progress_note,
    )


class ComposeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["resolved", "fragmented", "blocked"]
    finding: ProposedFinding | None = None
    child_questions: list[ChildQuestion] = []
    blocked_reason: str = ""
    progress_note: str

    @model_validator(mode="before")
    @classmethod
    def _migrate_misplaced_fields(cls, data):
        # Single-shot local models sometimes nest top-level fields inside
        # `finding` (observed: progress_note, smoke 2026-06-10). Migrate the
        # known fields out rather than fail the run on placement trivia; the
        # content itself is untouched and still strictly validated.
        if isinstance(data, dict) and isinstance(data.get("finding"), dict):
            nested = data["finding"]
            for key in ("progress_note", "outcome", "blocked_reason"):
                if key in nested and key not in data:
                    data[key] = nested.pop(key)
        return data


async def _single_shot_with_retry(what: str, postprocess=None, **session_kwargs):
    """Query-gen and compose are stateless one-shot calls — a malformed-JSON
    or schema-validation failure is a reroll, not a state hazard (observed:
    qwen3.5-9b-32k truncating mid-string, smoke 2026-06-10). Retry within the
    engine's standard transient policy, loudly; transport/timeout errors are
    handled in base.py and propagate unchanged. `postprocess(spawn)` runs
    inside the net: a ValueError from it (e.g. two-part compose parsing) is
    retryable like any other parse defect.

    Routes through run_role_session_with_fallback_async (2026-06-30, ultracode
    audit), not the bare run_role_session_async — these are the worker query-gen
    and compose roles, the highest-volume calls in the engine under the default
    worker_pipeline.enabled=true posture, and a primary-endpoint outage here used
    to crash the whole run uncaught instead of falling back, contradicting
    config.yaml's own 'driver-called worker/compose only' fallback comment."""
    run: Runspace = session_kwargs["run"]
    settings: Settings = session_kwargs["settings"]
    cycle: int = session_kwargs["cycle"]
    attempts = settings.retry.attempts
    last: SessionError | None = None
    for attempt in range(1, attempts + 1):
        try:
            spawn = await run_role_session_with_fallback_async(**session_kwargs)
            return postprocess(spawn) if postprocess else spawn
        except ValueError as exc:
            last = WorkerError(f"pipeline {what}: {exc}")
        except SessionError as exc:
            msg = str(exc)
            if "parseable JSON" not in msg and "failed validation" not in msg:
                raise
            last = exc
        if attempt < attempts:
            run.log(
                f"pipeline {what} (cycle {cycle}): output parse failed "
                f"(attempt {attempt}/{attempts}); retrying single-shot call"
            )
    raise last


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


# Social/UGC/video platforms: reliably 403, no extractable text, or
# non-citable for research (observed smoke7 2026-06-10: 7 of 12 reads burned
# on facebook posts and paywalled aggregators -> source_quality 5/10).
# Profiles can extend via url_preferences()["blocked_domains"].
_DEFAULT_BLOCKED_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "quora.com",
    "reddit.com",
    "threads.net",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)


_UNSET = object()
_RERANKER: Any = _UNSET


def _get_reranker():
    """Lazy FlashRank cross-encoder singleton (CPU/ONNX — never touches the
    GPU, so it can't contend with the resident worker/reader models). None if
    the optional dependency is missing."""
    global _RERANKER
    if _RERANKER is _UNSET:
        try:
            from rerankers import Reranker

            _RERANKER = Reranker("flashrank", verbose=0)
        except Exception:
            _RERANKER = None
    return _RERANKER


def rerank_scores(question: str, items: list[dict[str, Any]]) -> dict[str, float]:
    """normalized-url -> relevance score for each candidate's title+snippet
    against the question. Empty dict when reranking is unavailable or errors —
    selection then falls back to the pure authority/diversity rules. CPU-only
    and best-effort; a reranker fault must never fail a run."""
    ranker = _get_reranker()
    if ranker is None or not items:
        return {}
    docs: list[str] = []
    urls: list[str] = []
    for it in items:
        snippet = (str(it.get("title", "")) + " " + str(it.get("snippet", ""))).strip()
        url = (it.get("url") or "").strip()
        if snippet and url:
            docs.append(snippet[:500])
            urls.append(common.normalize_url(url))
    if not docs:
        return {}
    try:
        ranked = ranker.rank(query=question, docs=docs)
        return {urls[r.document.doc_id]: float(r.score) for r in ranked.results}
    except Exception:
        return {}


def _pipeline_cfg(settings: Settings, profile: Profile) -> dict[str, int]:
    cfg = {
        "queries_per_question": settings.worker_pipeline.queries_per_question,
        "urls_per_query": settings.worker_pipeline.urls_per_query,
        "max_reads": settings.worker_pipeline.max_reads,
        "per_domain_cap": settings.worker_pipeline.per_domain_cap,
    }
    for key, value in profile.pipeline_overrides().items():
        if key not in cfg:
            raise ConfigError(
                f"profile {profile.name!r} pipeline_overrides has unknown key {key!r}"
            )
        cfg[key] = int(value)
    return cfg


def select_urls(
    results_per_query: list[list[dict[str, Any]]],
    registry_urls: set[str],
    cfg: dict[str, int],
    preferences: dict[str, Any],
    question: str | None = None,
    rerank_fn: Any = None,
    *,
    stats: dict | None = None,
) -> list[dict[str, Any]]:
    """Rule-based URL selection (pure; spec step 3).

    Order: when a reranker is supplied, by question-relevance FIRST (so the
    read budget goes to the most on-target pages), then preferred domains as
    the tie-breaker; otherwise preferred domains first. Round-robin across
    queries either way. Dedupe by normalized URL; skip already-registered
    URLs; cap per domain (with profile overrides); cap total at max_reads.

    When `stats` is passed (spec §2.3 truncation instrumentation), it is
    populated in place with the per-reason drop breakdown: total_results,
    selected, dropped_{invalid,already_seen,per_query_cap,blocked,domain_cap,
    max_reads}. dropped_max_reads counts candidates never CONSIDERED once the
    read budget filled — the loop breaks there, so their would-be reasons are
    unknown by design."""
    preferred = list(preferences.get("preferred_domains", []))
    cap_overrides = dict(preferences.get("domain_cap_overrides", {}))
    blocked = set(_DEFAULT_BLOCKED_DOMAINS) | set(
        preferences.get("blocked_domains", [])
    )

    def is_blocked(domain: str) -> bool:
        return any(domain == b or domain.endswith("." + b) for b in blocked)

    def rank(item: dict[str, Any]) -> int:
        domain = _domain(item["url"])
        for i, pref in enumerate(preferred):
            if domain == pref or domain.endswith("." + pref):
                return i
        return len(preferred)

    # Pre-read relevance: score every candidate's snippet against the question
    # so on-target pages outrank merely high-authority but tangential ones.
    relevance: dict[str, float] = {}
    if question and rerank_fn is not None:
        all_items = [it for results in results_per_query for it in results]
        relevance = rerank_fn(question, all_items)

    seen: set[str] = set(registry_urls)
    domain_counts: dict[str, int] = {}
    per_query_kept: dict[int, int] = {}
    selected: list[dict[str, Any]] = []

    # Round-robin across query result lists so one query can't starve others.
    indexes = [0] * len(results_per_query)
    ordered: list[tuple[int, dict[str, Any]]] = []
    progressed = True
    while progressed:
        progressed = False
        for qi, results in enumerate(results_per_query):
            if indexes[qi] < len(results):
                ordered.append((qi, results[indexes[qi]]))
                indexes[qi] += 1
                progressed = True
    # Relevance descending (primary), domain-authority ascending (tie-break).
    # When relevance is empty (reranker off/unavailable), all scores are 0.0
    # and this reduces exactly to the prior authority-first ordering.
    def sort_key(pair: tuple[int, dict[str, Any]]):
        norm = common.normalize_url((pair[1].get("url") or "").strip())
        return (-relevance.get(norm, 0.0), rank(pair[1]))

    ordered.sort(key=sort_key)

    drops: Counter[str] = Counter()
    budget_full_at: int | None = None

    for position, (qi, item) in enumerate(ordered):
        url = (item.get("url") or "").strip()
        if not url or not url.startswith("http"):
            drops["invalid"] += 1
            continue
        normalized = common.normalize_url(url)
        if normalized in seen:
            drops["already_seen"] += 1
            continue
        if per_query_kept.get(qi, 0) >= cfg["urls_per_query"]:
            drops["per_query_cap"] += 1
            continue
        domain = _domain(url)
        if is_blocked(domain):
            drops["blocked"] += 1
            continue
        cap = int(cap_overrides.get(domain, cfg["per_domain_cap"]))
        if domain_counts.get(domain, 0) >= cap:
            drops["domain_cap"] += 1
            continue
        seen.add(normalized)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        per_query_kept[qi] = per_query_kept.get(qi, 0) + 1
        selected.append(item)
        if len(selected) >= cfg["max_reads"]:
            budget_full_at = position
            break

    if stats is not None:
        stats.update(
            total_results=sum(len(r) for r in results_per_query),
            selected=len(selected),
            dropped_invalid=drops["invalid"],
            dropped_already_seen=drops["already_seen"],
            dropped_per_query_cap=drops["per_query_cap"],
            dropped_blocked=drops["blocked"],
            dropped_domain_cap=drops["domain_cap"],
            dropped_max_reads=(
                len(ordered) - budget_full_at - 1
                if budget_full_at is not None
                else 0
            ),
        )
    return selected


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def build_engine_sources(
    reads: list[tuple[str, reader.ReaderOutput]],
    registry: SourceRegistry | None = None,
) -> list[dict[str, Any]]:
    """Spec step 5: the ENGINE builds the sources array from reader metadata.
    Ids are slugified from titles and uniqued against BOTH this batch and the
    run's existing registry — generic SEO titles collide across cycles
    (observed smoke 2026-06-10: two 'how long do electric car batteries
    last' pages from different domains). A URL already in the registry
    reuses its existing id; urls are always the URLs actually read."""
    taken: set[str] = set()
    id_by_norm_url: dict[str, str] = {}
    if registry is not None:
        for sid, rec in registry.root.items():
            taken.add(sid)
            id_by_norm_url.setdefault(common.normalize_url(rec.url), sid)
    sources: list[dict[str, Any]] = []
    for url, output in reads:
        norm = common.normalize_url(url)
        # Readers occasionally return an empty title (untitled pages —
        # observed smoke14 2026-06-11: SourceRecord.title min_length=1 killed
        # the run). Derive one from the URL; the URL is always real.
        title = output.title.strip() or _domain(url) + urlparse(url).path[:60]
        if norm in id_by_norm_url:
            source_id = id_by_norm_url[norm]
        else:
            base = _SLUG_RE.sub("-", title.lower()).strip("-")[:40].strip("-") or "source"
            source_id = f"src-{base}"
            n = 2
            while source_id in taken:
                source_id = f"src-{base}-{n}"
                n += 1
            id_by_norm_url[norm] = source_id
        taken.add(source_id)
        sources.append(
            {
                "id": source_id,
                "url": url,
                "title": title,
                "kind": output.kind,
                "credibility": output.credibility,
                "notes": output.notes,
                # Span-level citation anchors (roadmap): already engine-verified
                # verbatim against the page text in reader.read_source.
                "excerpts": output.key_quotes,
            }
        )
    return sources


async def _gather_results(
    providers: list[tuple[str, Any]],
    queries: list[str],
    run: Runspace,
) -> list[list[dict[str, Any]]]:
    """One result list per query, concatenating providers in profile order.
    Provider failures are logged, never fatal — the read fan-out decides
    whether the run is actually blocked."""
    async def per_query(query: str) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for name, fn in providers:
            try:
                merged.extend(await fn(query))
            except Exception as exc:  # noqa: BLE001 — log + continue per provider
                run.log(f"pipeline search provider {name} failed for {query!r}: {exc}")
        return merged

    return list(await asyncio.gather(*(per_query(q) for q in queries)))


def run_pipeline(
    run: Runspace,
    settings: Settings,
    cycle: int,
    ledger: Ledger,
    target: OpenQuestion,
    profile: Profile,
) -> SessionResult:
    result, outage = asyncio.run(
        _run_pipeline_async(run, settings, cycle, ledger, target, profile)
    )
    # Sequential mode: one question IS the cycle, so its observation is the
    # cycle's observation (identical semantics to the pre-aggregation code).
    if outage is not None:
        run.note_read_outage(outage)
    return result


def run_pipeline_batch(
    run: Runspace,
    settings: Settings,
    cycle: int,
    ledger: Ledger,
    targets: list[OpenQuestion],
    profile: Profile,
) -> list[SessionResult | BaseException]:
    """Investigate several questions CONCURRENTLY in one event loop (roadmap:
    parallel worker fan-out). The wall-clock win comes from overlapping each
    question's search/read/compose AWAITS; correctness is free because every
    state-mutating apply section (merge_sources / write_finding / save_questions)
    is synchronous — asyncio's cooperative scheduler cannot preempt an await-free
    block, so two questions' applies never interleave mid-write and no lock is
    needed. return_exceptions keeps one bad question from killing the batch; the
    caller leaves a failed question for the next cycle (the orphan picker re-claims
    its in_progress status).

    Read-outage aggregation (final review): the streak breaker counts
    consecutive CYCLES, so the batch notes the outage ONCE per cycle — a cycle
    is an outage only if at least one question selected reads AND every such
    question had ALL its reads fail. Per-question noting incremented the streak
    K times per genuinely-bad cycle (killing a K=3 run after ONE cycle) and made
    the final value depend on completion order."""

    async def _gather() -> list[tuple[SessionResult, bool | None] | BaseException]:
        return await asyncio.gather(
            *(
                _run_pipeline_async(run, settings, cycle, ledger, t, profile)
                for t in targets
            ),
            return_exceptions=True,
        )

    raw = asyncio.run(_gather())
    results: list[SessionResult | BaseException] = []
    observations: list[bool] = []
    for item in raw:
        if isinstance(item, BaseException):
            results.append(item)  # errored questions are outage-neutral
            continue
        result, outage = item
        results.append(result)
        if outage is not None:  # questions with zero selected reads are neutral
            observations.append(outage)
    if observations:
        run.note_read_outage(all(observations))
    return results


async def _run_pipeline_async(
    run: Runspace,
    settings: Settings,
    cycle: int,
    ledger: Ledger,
    target: OpenQuestion,
    profile: Profile,
) -> tuple[SessionResult, bool | None]:
    """Investigate ONE question. Returns (result, outage_observation) where the
    observation is True if every selected read failed to fetch, False if any
    fetched, None if no reads were selected — the ORCHESTRATOR (run_pipeline /
    run_pipeline_batch) aggregates observations and notes the per-CYCLE outage
    streak exactly once, so parallel fan-out can't multiply it (final review)."""
    cfg = _pipeline_cfg(settings, profile)
    # Community-track questions search forums via their lens; factual questions
    # use the profile's providers (docs/COMMUNITY_LENS_SPEC.md). Default runs
    # only ever have factual questions, so this is the profile path as before.
    providers = profile.pipeline_search_providers(settings)
    if target.track != "factual":
        from src.lenses import lens_for_track

        lens = lens_for_track(target.track, settings.lenses)
        if lens is not None:
            providers = lens.search_providers(settings)
    role_cfg = settings.roles[_ROLE]

    # --- step 1: one-shot query-gen --------------------------------------------
    registry = run.load_sources()
    plan = (run.root / PLAN_FILE).read_text(encoding="utf-8")
    query_prompt = (
        f"# Assigned question\n{target.id} [priority {target.priority}]: "
        f"{target.question}\n\n"
        f"# Research question (overall)\n{run.meta.question}\n\n"
        f"# Research plan (context)\n{plan}\n\n"
        f"# Domain guidance (profile: {profile.name})\n{profile.worker_guidance()}\n\n"
        f"# Sources already in the registry (avoid re-finding these)\n"
        f"{common.sources_digest(registry)}\n\n"
        f"Generate up to {cfg['queries_per_question']} queries."
    )
    query_spawn = await _single_shot_with_retry(
        "query-gen",
        run=run, settings=settings, ledger=ledger, cycle=cycle,
        session_type="worker", role=_ROLE,
        system_prompt=_QUERY_GEN_SYSTEM, user_prompt=query_prompt,
        tools=[], output_model=QueryGenOutput,
    )
    queries = [q.strip() for q in query_spawn.structured.queries if q.strip()]
    if not queries:
        raise WorkerError(f"{target.id}: query-gen returned zero queries")
    if len(queries) > cfg["queries_per_question"]:
        run.log_decision(
            f"pipeline (cycle {cycle}): query-gen returned {len(queries)} queries; "
            f"truncated to {cfg['queries_per_question']}"
        )
        queries = queries[: cfg["queries_per_question"]]

    # --- steps 2-3: engine search + rule-based selection ------------------------
    results_per_query = await _gather_results(providers, queries, run)
    total_results = sum(len(r) for r in results_per_query)
    registry_urls = {common.normalize_url(rec.url) for rec in registry.root.values()}
    rerank_fn = rerank_scores if settings.worker_pipeline.rerank else None
    sel_stats: dict = {}
    selected = select_urls(
        results_per_query, registry_urls, cfg, profile.url_preferences(),
        question=target.question, rerank_fn=rerank_fn, stats=sel_stats,
    )
    if total_results > len(selected):
        run.log_decision(
            f"pipeline (cycle {cycle}): read budget {cfg['max_reads']} truncated "
            f"{total_results} candidates -> {len(selected)} selected "
            f"(dropped: {sel_stats.get('dropped_max_reads', 0)} over-budget, "
            f"{sel_stats.get('dropped_domain_cap', 0)} domain-cap, "
            f"{sel_stats.get('dropped_per_query_cap', 0)} per-query-cap, "
            f"{sel_stats.get('dropped_blocked', 0)} blocked, "
            f"{sel_stats.get('dropped_already_seen', 0)} already-seen, "
            f"{sel_stats.get('dropped_invalid', 0)} invalid)"
        )

    # --- step 4: reader fan-out (existing machinery) ----------------------------
    read_urls: set[str] = set()
    reads: list[tuple[str, reader.ReaderOutput]] = []
    failures = 0

    async def read_one(item: dict[str, Any]) -> None:
        nonlocal failures
        url = item["url"]
        try:
            output, _spawn = await reader.read_source(
                run=run, settings=settings, ledger=ledger, cycle=cycle,
                url=url, question=target.question, why=item.get("snippet", "")[:200],
            )
        except SessionError as exc:
            failures += 1
            run.log(f"pipeline read failed ({url}): {exc}")
            return
        if output.useful:
            read_urls.add(common.normalize_url(url))
            reads.append((url, output))

    await asyncio.gather(*(read_one(item) for item in selected))

    # Circuit-breaker signal (audit #20): if EVERY selected URL failed to fetch
    # (not "fetched but judged unhelpful"), the volume/reader endpoint is likely
    # down, not the web. RETURNED to the orchestrator (not noted here) so the
    # consecutive-cycle streak is updated once per CYCLE, never once per
    # question (final review: K parallel questions tripped the K>=3 breaker
    # after a single bad cycle, nondeterministically with completion order).
    outage_observation: bool | None = (failures == len(selected)) if selected else None

    summary_prefix = (
        f"pipeline: {len(queries)} queries, {total_results} results, "
        f"{len(selected)} selected, {len(reads)} useful reads, {failures} failed"
    )

    # --- engine pre-emption: nothing useful was read -----------------------------
    if not reads:
        # HARD block when the engine actually READ pages this cycle (fetched
        # successfully) and the reader judged none useful — the facet isn't
        # answerable from what's out there, not merely a transient fetch blip.
        pages_read = len(selected) - failures
        hard_block = pages_read >= 3
        run.log_decision(
            f"pipeline (cycle {cycle}): 0/{len(selected)} useful reads for "
            f"{target.id} ({pages_read} read, none useful) — engine-blocked "
            f"without compose ({'HARD' if hard_block else 'soft'})"
        )
        fake = ComposeOutput(
            outcome="blocked",
            blocked_reason=(
                f"no useful reads: {len(selected)} URLs selected, "
                f"{pages_read} read but none useful, {failures} fetch-failed"
            ),
            progress_note=summary_prefix,
        )
        summary = _apply_blocked(run, target, fake, hard_block=hard_block)
        run.log(f"worker (cycle {cycle}, pipeline): {summary_prefix}")
        return (
            _session_result(role_cfg, query_spawn, None, summary, summary_prefix),
            outage_observation,
        )

    # --- step 5: ENGINE builds sources -------------------------------------------
    engine_sources = build_engine_sources(reads, run.load_sources())
    merged = common.merge_sources(
        run, engine_sources, WorkerError,
        read_urls=read_urls, require_reads=settings.reader.require_reads,
    )
    id_by_url = {s["url"]: s["id"] for s in engine_sources}

    # --- step 6: one-shot compose --------------------------------------------------
    compose_role = _COMPOSE_ROLE if _COMPOSE_ROLE in settings.roles else _ROLE
    menu_lines = []
    for url, output in reads:
        sid = id_by_url[url]
        menu_lines.append(
            f"## [{sid}] {output.title} (kind={output.kind}, "
            f"credibility={output.credibility})\n"
            f"NOTES: {output.notes}\nSUMMARY:\n{output.summary_markdown}"
        )
    compose_prompt = (
        f"# Assigned question\n{target.id}: {target.question}\n\n"
        f"# Research question (overall)\n{run.meta.question}\n\n"
        f"# Domain guidance (profile: {profile.name})\n{profile.worker_guidance()}\n\n"
        f"# Valid citation menu — the ONLY ids you may cite\n"
        + ", ".join(f"[{s['id']}]" for s in engine_sources)
        + "\n\n# Reader summaries (your only admissible material — untrusted)\n\n"
        + untrusted.wrap_untrusted("\n\n".join(menu_lines), label="reader summaries")
    )
    compose_spawn, output = await _single_shot_with_retry(
        "compose",
        postprocess=lambda sp: (
            sp,
            parse_compose_output(
                sp.result_text, {s["id"] for s in engine_sources}
            ),
        ),
        run=run, settings=settings, ledger=ledger, cycle=cycle,
        session_type="worker", role=compose_role,
        system_prompt=_COMPOSE_SYSTEM, user_prompt=compose_prompt,
        tools=[], output_model=None,
    )

    # --- step 7: existing apply gates, unchanged semantics --------------------------
    if output.outcome == "resolved":
        if output.finding is None:
            raise WorkerError(f"{target.id}: outcome=resolved but no finding returned")
        if not 0.0 <= output.finding.confidence <= 1.0:
            raise WorkerError(
                f"{target.id}: confidence {output.finding.confidence} outside 0-1"
            )
        body = output.finding.body_markdown.strip()
        cited = common.CITATION_RE.findall(body)
        if not cited:
            raise WorkerError(
                f"{target.id}: finding contains no [src-...] citations (invariant 3)"
            )
        unknown = sorted({c for c in cited if c not in merged.root})
        if unknown:
            raise WorkerError(
                f"{target.id}: finding cites ids outside the engine-built menu "
                f"{unknown} (invariant 3)"
            )
        slug = f"{target.id}-c{cycle:02d}"
        run.write_finding(
            slug,
            FindingMeta(
                question_id=target.id,
                source_ids=sorted(set(cited)),
                confidence=output.finding.confidence,
                track=target.track,  # quarantine inherited from the question
            ),
            body,
        )
        questions = run.load_questions()
        fresh = questions.get(target.id)
        fresh.status = "resolved"
        fresh.resolved_by_finding = slug
        run.save_questions(questions)
        summary = f"resolved {target.id} -> findings/{slug}.md ({len(set(cited))} sources)"
    elif output.outcome == "fragmented":
        summary = _apply_fragmented(run, settings, target, output)
    else:  # "blocked" — the only remaining Literal variant
        summary = _apply_blocked(run, target, output)

    run.log(
        f"worker (cycle {cycle}, pipeline): {output.progress_note} [{summary_prefix}]"
    )
    return (
        _session_result(role_cfg, query_spawn, compose_spawn, summary, summary_prefix),
        outage_observation,
    )


def _session_result(role_cfg, query_spawn, compose_spawn, summary, prefix) -> SessionResult:
    spawns = [s for s in (query_spawn, compose_spawn) if s is not None]
    return SessionResult(
        session_type="worker",
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        input_tokens=sum(s.input_tokens for s in spawns),
        output_tokens=sum(s.output_tokens for s in spawns),
        cached_tokens=sum(s.cached_tokens for s in spawns),
        usd=sum(s.usd for s in spawns),
        wall_seconds=sum(s.wall_seconds for s in spawns),
        summary=f"{summary} [{prefix}]",
    )


__all__ = [
    "ComposeOutput",
    "QueryGenOutput",
    "build_engine_sources",
    "run_pipeline",
    "select_urls",
]
