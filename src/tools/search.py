"""SearXNG-backed web search — the MCP search fallback for workers routed to
non-first-party endpoints, where Anthropic-hosted WebSearch does not exist
(CLAUDE.md §1 local-mode constraints)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.settings import RetryCfg, Settings
from src.tools import ConnectorError, http_get_with_retry


def parse_searxng_results(payload: dict, max_results: int) -> list[dict[str, Any]]:
    try:
        results = payload.get("results", [])[:max_results]
        return [
            {
                "title": r.get("title", "(untitled)"),
                "url": r.get("url", ""),
                "snippet": (r.get("content") or "")[:400],
            }
            for r in results
        ]
    except (AttributeError, TypeError) as exc:
        raise ConnectorError(f"unexpected SearXNG payload: {exc}") from exc


def format_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "web_search: no results."
    lines = [f"web_search: {len(results)} results"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   URL: {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)


async def searxng_results(
    base_url: str, query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> list[dict[str, Any]]:
    """Normalized raw results for pipeline-mode URL selection."""
    try:
        response = await http_get_with_retry(
            base_url.rstrip("/") + "/search",
            retry_cfg=retry_cfg,
            timeout=timeout,
            params={"q": query, "format": "json"},
        )
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise ConnectorError(f"SearXNG search failed ({base_url}): {exc}") from exc
    return parse_searxng_results(payload, max_results)


async def searxng_search(
    base_url: str, query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> str:
    try:
        response = await http_get_with_retry(
            base_url.rstrip("/") + "/search",
            retry_cfg=retry_cfg,
            timeout=timeout,
            params={"q": query, "format": "json"},
        )
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise ConnectorError(f"SearXNG search failed ({base_url}): {exc}") from exc
    return format_results(parse_searxng_results(payload, max_results))


def build_search_mcp(settings: Settings):
    """In-process MCP server exposing web_search via the configured SearXNG."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    base_url = settings.search.searxng_base_url
    if not base_url:
        raise ConnectorError(
            "search fallback requested but search.searxng_base_url is not set"
        )
    timeout = settings.reader.fetch_timeout_seconds
    max_results = settings.search.max_results

    @tool(
        "web_search",
        "Search the web (SearXNG). Returns titles, URLs and snippets; feed "
        "promising URLs into read_source.",
        {"query": str},
    )
    async def web_search(args: dict) -> dict:
        query = str(args.get("query", "")).strip()
        if not query:
            return {"content": [{"type": "text", "text": "web_search: empty query"}],
                    "is_error": True}
        try:
            text = await searxng_search(
                base_url, query, max_results, timeout, settings.retry
            )
        except ConnectorError as exc:
            return {"content": [{"type": "text", "text": f"SEARCH FAILED: {exc}"}],
                    "is_error": True}
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server("search", tools=[web_search])
