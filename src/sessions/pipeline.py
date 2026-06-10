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
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from src.errors import ConfigError
from src.ledger import Ledger
from src.profiles import Profile
from src.runspace import PLAN_FILE, Runspace
from src.sessions import common, reader
from src.sessions.base import (
    SessionError,
    SessionResult,
    WorkerError,
    run_role_session_async,
)
from src.sessions.worker import (
    ChildQuestion,
    ProposedFinding,
    _apply_blocked,
    _apply_fragmented,
)
from src.settings import Settings
from src.state import FindingMeta, OpenQuestion

_ROLE = "worker"

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

finding.confidence: 0.0-1.0. progress_note: one line for the run log.
Respond ONLY via the enforced JSON schema."""


class QueryGenOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str]
    notes: str


class ComposeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["resolved", "fragmented", "blocked"]
    finding: ProposedFinding | None = None
    child_questions: list[ChildQuestion] = []
    blocked_reason: str = ""
    progress_note: str


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


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
) -> list[dict[str, Any]]:
    """Rule-based URL selection (pure; spec step 3).

    Order: preferred domains first, then provider order, round-robin across
    queries. Dedupe by normalized URL; skip already-registered URLs; cap per
    domain (with profile overrides); cap total at max_reads."""
    preferred = list(preferences.get("preferred_domains", []))
    cap_overrides = dict(preferences.get("domain_cap_overrides", {}))

    def rank(item: dict[str, Any]) -> int:
        domain = _domain(item["url"])
        for i, pref in enumerate(preferred):
            if domain == pref or domain.endswith("." + pref):
                return i
        return len(preferred)

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
    ordered.sort(key=lambda pair: rank(pair[1]))

    for qi, item in ordered:
        url = (item.get("url") or "").strip()
        if not url or not url.startswith("http"):
            continue
        normalized = common.normalize_url(url)
        if normalized in seen:
            continue
        if per_query_kept.get(qi, 0) >= cfg["urls_per_query"]:
            continue
        domain = _domain(url)
        cap = int(cap_overrides.get(domain, cfg["per_domain_cap"]))
        if domain_counts.get(domain, 0) >= cap:
            continue
        seen.add(normalized)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        per_query_kept[qi] = per_query_kept.get(qi, 0) + 1
        selected.append(item)
        if len(selected) >= cfg["max_reads"]:
            break
    return selected


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def build_engine_sources(
    reads: list[tuple[str, reader.ReaderOutput]],
) -> list[dict[str, Any]]:
    """Spec step 5: the ENGINE builds the sources array from reader metadata.
    Ids are slugified from titles and uniqued; urls are the URLs actually
    read. Returns merge_sources-shaped dicts."""
    sources: list[dict[str, Any]] = []
    taken: set[str] = set()
    for url, output in reads:
        base = _SLUG_RE.sub("-", output.title.lower()).strip("-")[:40].strip("-") or "source"
        source_id = f"src-{base}"
        n = 2
        while source_id in taken:
            source_id = f"src-{base}-{n}"
            n += 1
        taken.add(source_id)
        sources.append(
            {
                "id": source_id,
                "url": url,
                "title": output.title,
                "kind": output.kind,
                "credibility": output.credibility,
                "notes": output.notes,
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
    return asyncio.run(
        _run_pipeline_async(run, settings, cycle, ledger, target, profile)
    )


async def _run_pipeline_async(
    run: Runspace,
    settings: Settings,
    cycle: int,
    ledger: Ledger,
    target: OpenQuestion,
    profile: Profile,
) -> SessionResult:
    cfg = _pipeline_cfg(settings, profile)
    providers = profile.pipeline_search_providers(settings)
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
    query_spawn = await run_role_session_async(
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
    selected = select_urls(results_per_query, registry_urls, cfg, profile.url_preferences())
    if total_results > 0 and len(selected) == cfg["max_reads"]:
        run.log_decision(
            f"pipeline (cycle {cycle}): read budget {cfg['max_reads']} truncated "
            f"{total_results} candidates"
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

    summary_prefix = (
        f"pipeline: {len(queries)} queries, {total_results} results, "
        f"{len(selected)} selected, {len(reads)} useful reads, {failures} failed"
    )

    # --- engine pre-emption: nothing useful was read -----------------------------
    if not reads:
        run.log_decision(
            f"pipeline (cycle {cycle}): 0/{len(selected)} useful reads for "
            f"{target.id} — engine-blocked without compose"
        )
        fake = ComposeOutput(
            outcome="blocked",
            blocked_reason=(
                f"no useful reads: {len(selected)} URLs selected, "
                f"{failures} reads failed"
            ),
            progress_note=summary_prefix,
        )
        summary = _apply_blocked(run, target, fake)
        run.log(f"worker (cycle {cycle}, pipeline): {summary_prefix}")
        return _session_result(role_cfg, query_spawn, None, summary, summary_prefix)

    # --- step 5: ENGINE builds sources -------------------------------------------
    engine_sources = build_engine_sources(reads)
    merged = common.merge_sources(
        run, engine_sources, WorkerError,
        read_urls=read_urls, require_reads=settings.reader.require_reads,
    )
    id_by_url = {s["url"]: s["id"] for s in engine_sources}

    # --- step 6: one-shot compose --------------------------------------------------
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
        + "\n\n# Reader summaries (your only admissible material)\n\n"
        + "\n\n".join(menu_lines)
    )
    compose_spawn = await run_role_session_async(
        run=run, settings=settings, ledger=ledger, cycle=cycle,
        session_type="worker", role=_ROLE,
        system_prompt=_COMPOSE_SYSTEM, user_prompt=compose_prompt,
        tools=[], output_model=ComposeOutput,
    )
    output: ComposeOutput = compose_spawn.structured

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
        summary = _apply_fragmented(run, target, output)
    else:  # "blocked" — the only remaining Literal variant
        summary = _apply_blocked(run, target, output)

    run.log(
        f"worker (cycle {cycle}, pipeline): {output.progress_note} [{summary_prefix}]"
    )
    return _session_result(role_cfg, query_spawn, compose_spawn, summary, summary_prefix)


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
