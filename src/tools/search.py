"""SearXNG-backed web search — the MCP search fallback for workers routed to
non-first-party endpoints, where Anthropic-hosted WebSearch does not exist
(CLAUDE.md §1 local-mode constraints)."""

from __future__ import annotations

from typing import Any

import httpx

from src.settings import RetryCfg, Settings
from src.tools import ConnectorError, http_get_with_retry, http_post_with_retry


def _decode_json(response: httpx.Response, label: str) -> Any:
    """Decode a response body as JSON, turning ANY decode failure into a clean
    ConnectorError. response.json() can raise more than JSONDecodeError: a bogus
    Content-Encoding/charset makes the decoder raise UnicodeDecodeError / LookupError
    / AssertionError, none of which subclass httpx.HTTPError, so the old narrow
    `except (httpx.HTTPError, json.JSONDecodeError)` let them escape and crash a
    worker session (the exact bug fixed in reader.py 72c5546 and ported to
    academic.py 9192bd1 — ported here too, audit #3, 2026-06-30)."""
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001 — any decode failure means an unusable body
        raise ConnectorError(f"{label} returned an undecodable body: {exc!r}") from exc


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
    except httpx.HTTPError as exc:
        raise ConnectorError(f"SearXNG search failed ({base_url}): {exc}") from exc
    payload = _decode_json(response, f"SearXNG ({base_url})")
    return parse_searxng_results(payload, max_results)


async def ddg_results(
    query: str, max_results: int, timeout: float = 10.0
) -> list[dict[str, Any]]:
    """Docker-free fallback search via DuckDuckGo (ddgs). No API key, no container
    — keeps pipeline search working when SearXNG/Docker is down. Lower breadth than
    SearXNG's multi-engine aggregation, so it is the fallback, never the primary.
    ddgs is synchronous; run it off the event loop so the pipeline stays async."""
    import asyncio

    def _blocking() -> list[dict[str, Any]]:
        from ddgs import DDGS

        out: list[dict[str, Any]] = []
        for r in DDGS(timeout=timeout).text(query, max_results=max_results):
            out.append(
                {
                    "title": r.get("title", "(untitled)"),
                    "url": r.get("href") or r.get("url", ""),
                    "snippet": (r.get("body") or "")[:400],
                }
            )
        return out

    try:
        return await asyncio.to_thread(_blocking)
    except Exception as exc:  # noqa: BLE001 — any ddgs failure is a search failure
        raise ConnectorError(f"DuckDuckGo search failed: {exc}") from exc


def parse_serper_results(payload: dict, max_results: int) -> list[dict[str, Any]]:
    """Serper returns Google's SERP as JSON. We take the `organic` block — the
    title/link/snippet are exactly the (title, url, snippet) the pipeline needs to
    rank and then deep-read. Snippets are only for URL SELECTION here; the engine's
    own reader fetches each chosen page in full, so 150-char snippets are enough
    (the usual 'SERP snippets are too thin for an agent' caveat assumes no reader)."""
    try:
        organic = payload.get("organic", [])[:max_results]
        return [
            {
                "title": r.get("title", "(untitled)"),
                "url": r.get("link", ""),
                "snippet": (r.get("snippet") or "")[:400],
            }
            for r in organic
            if r.get("link")
        ]
    except (AttributeError, TypeError) as exc:
        raise ConnectorError(f"unexpected Serper payload: {exc}") from exc


async def serper_results(
    api_key: str,
    query: str,
    max_results: int,
    timeout: float,
    retry_cfg: RetryCfg,
    *,
    endpoint: str = "https://google.serper.dev/search",
    gl: str = "us",
    hl: str = "en",
) -> list[dict[str, Any]]:
    """Google SERP via Serper (the portable, key-based primary web provider).
    Google's index is the broadest single source, and Serper is cheap enough
    (~$0.0003/query) that breadth comes from issuing MANY queries, not one fat one
    — so we cap `num` at the pipeline's max_results, not Serper's 100 max."""
    body = {
        "q": query,
        "num": min(max(max_results, 10), 100),
        "gl": gl,
        "hl": hl,
    }
    try:
        response = await http_post_with_retry(
            endpoint,
            retry_cfg=retry_cfg,
            timeout=timeout,
            json_body=body,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Serper search failed: {exc}") from exc
    payload = _decode_json(response, "Serper")
    return parse_serper_results(payload, max_results)


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
    except httpx.HTTPError as exc:
        raise ConnectorError(f"SearXNG search failed ({base_url}): {exc}") from exc
    payload = _decode_json(response, f"SearXNG ({base_url})")
    return format_results(parse_searxng_results(payload, max_results))


def preflight_search(settings: Settings, *, timeout: float = 6.0) -> str:
    """Ensure SOME search backend works before spending; return which one.

    Pipeline mode requires engine-side search (Anthropic-hosted WebSearch never
    exists there, §1). Without it every worker cycle blocks with zero reads and
    the run burns its whole cycle budget to synthesize an empty report. Preference
    order: Serper (portable Google API, when SERPER_API_KEY is set) -> SearXNG
    (self-host) -> DuckDuckGo (free fallback). Abort only if NONE answers. Returns
    "serper" | "searxng" | "ddg" so the caller can warn on a degraded fallback."""
    import asyncio

    from src.errors import ConfigError

    # Serper first — the preferred web backend when a key is present. A live probe
    # (one ~$0.0003 credit) catches a bad/expired key NOW rather than mid-run.
    serper_env = settings.search.serper_api_key_env
    serper_key = settings.secrets.get(serper_env) if serper_env else None
    serper_err: str | None = None
    if serper_key:
        try:
            response = httpx.post(
                settings.search.serper_endpoint,
                json={"q": "connectivity check", "num": 1,
                      "gl": settings.search.serper_gl, "hl": settings.search.serper_hl},
                headers={"X-API-KEY": serper_key.get_secret_value(),
                         "Content-Type": "application/json"},
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            serper_err = str(exc)
        else:
            try:
                response.json()
            except Exception as exc:  # noqa: BLE001 — an undecodable body
                # (UnicodeDecodeError/LookupError from a bogus charset) just means
                # "this backend isn't usable"; record it and fall to the next.
                serper_err = str(exc)
            else:
                return "serper"

    base_url = settings.search.searxng_base_url
    searxng_err: str | None = None
    if base_url:
        try:
            response = httpx.get(
                base_url.rstrip("/") + "/search",
                params={"q": "connectivity check", "format": "json"},
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            searxng_err = str(exc)
        else:
            try:
                response.json()  # JSON output must be enabled — the engine parses it
            except Exception as exc:  # noqa: BLE001 — see serper probe above
                searxng_err = str(exc)
            else:
                return "searxng"

    # Serper/SearXNG down or unconfigured — verify the Docker-free DDG fallback.
    try:
        if asyncio.run(ddg_results("connectivity check", 1, timeout)):
            return "ddg"
        ddg_err = "returned no results"
    except ConnectorError as exc:
        ddg_err = str(exc)

    raise ConfigError(
        "no search backend is reachable.\n"
        f"  Serper: {serper_err or 'no SERPER_API_KEY in .env (set one for Google search)'}\n"
        f"  SearXNG: {searxng_err or 'not configured'}\n"
        f"  DuckDuckGo fallback: {ddg_err}\n"
        "  Set SERPER_API_KEY (serper.dev, free tier), start SearXNG "
        "(docker start searxng), or check connectivity. Bypass with --skip-search-check."
    )


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
