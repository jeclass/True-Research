"""Profile interface (CLAUDE.md §7): tools(), rubric(), worker_guidance().

A profile decides which tools the worker session gets (built-in names plus
in-process MCP servers), what the evaluator demands, and the domain
instructions injected into the worker prompt. The engine-owned reader
(read_source) is attached by the worker itself for every profile."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from src.errors import ConfigError
from src.ledger import Ledger
from src.runspace import Runspace
from src.settings import Settings
from src.state import OpenQuestion

_FILE_TOOLS = ["Read", "Glob", "Grep"]


@dataclass(frozen=True)
class WorkerToolContext:
    """Everything a profile's in-process MCP tools may need: the run, the
    ledger (every model-backed tool call is ledgered), and the worker's
    read-tracking state for the read-gate."""

    run: Runspace
    settings: Settings
    ledger: Ledger
    cycle: int
    target: OpenQuestion
    stats: dict[str, int]
    read_urls: set[str]


@dataclass
class WorkerToolset:
    builtin: list[str]
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    extra_allowed: list[str] = field(default_factory=list)


def search_tools(settings: Settings) -> WorkerToolset:
    """Web search appropriate to the worker's endpoint: Anthropic-hosted
    WebSearch on first-party, SearXNG MCP fallback otherwise (§1 — WebSearch
    does not exist against non-first-party endpoints). No silent degradation:
    a local-routed worker with no fallback configured is a ConfigError."""
    worker_endpoint = settings.endpoints[settings.role("worker").endpoint]
    if worker_endpoint.base_url is None:
        return WorkerToolset(builtin=["WebSearch"])
    if settings.search.searxng_base_url:
        from src.tools.search import build_search_mcp

        return WorkerToolset(
            builtin=[],
            mcp_servers={"search": build_search_mcp(settings)},
            extra_allowed=["mcp__search__web_search"],
        )
    raise ConfigError(
        "worker is routed to a non-first-party endpoint, where Anthropic-hosted "
        "WebSearch does not exist (§1) — configure search.searxng_base_url or "
        "route the worker role back to a first-party endpoint"
    )


class Profile(ABC):
    name: ClassVar[str]

    # --- pipeline-worker hooks (docs/PIPELINE_WORKER_SPEC.md) ---------------

    def pipeline_search_providers(self, settings: Settings) -> list[tuple[str, Any]]:
        """(name, async fn(query) -> [{title,url,snippet}]) the engine queries in
        pipeline mode. Anthropic-hosted WebSearch never exists engine-side (§1), so
        this is SearXNG (70+-engine aggregation) with a Docker-free DuckDuckGo
        fallback: SearXNG is tried first when configured, and on failure/empty the
        provider falls back to DDG so research survives a SearXNG/Docker outage.
        DDG only fires when SearXNG misses, so there's no double-querying."""
        from src.tools import ConnectorError
        from src.tools.search import ddg_results, searxng_results

        base_url = settings.search.searxng_base_url
        max_results = settings.search.max_results
        timeout = settings.reader.fetch_timeout_seconds

        async def _search(query: str):
            if base_url:
                try:
                    results = await searxng_results(
                        base_url, query, max_results, timeout, settings.retry
                    )
                    if results:
                        return results
                    # SearXNG up but no hits — let DDG take a swing before giving up
                except ConnectorError:
                    pass  # SearXNG down (e.g. Docker stopped) -> DDG fallback
            return await ddg_results(query, max_results, timeout)

        return [("search", _search)]

    def url_preferences(self) -> dict[str, Any]:
        """Ranking hints for pipeline URL selection: preferred_domains are
        ranked first; domain_cap_overrides relax the per-domain cap."""
        return {"preferred_domains": [], "domain_cap_overrides": {}}

    def pipeline_overrides(self) -> dict[str, int]:
        """Per-profile overrides of worker_pipeline numeric knobs."""
        return {}

    @abstractmethod
    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        """Tools for the worker session (search + file tools + domain MCP)."""

    @abstractmethod
    def rubric(self) -> str:
        """What the evaluator demands for this domain (injected verbatim)."""

    @abstractmethod
    def worker_guidance(self) -> str:
        """Domain instructions injected into the worker system prompt."""

    def _base_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        toolset = search_tools(ctx.settings)
        toolset.builtin = toolset.builtin + _FILE_TOOLS
        return toolset
