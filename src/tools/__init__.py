"""Custom tool / MCP wiring (CLAUDE.md §2, Phase 4). In-process MCP servers
the profiles attach to worker sessions. Connector fetches are engine-side
httpx; failures surface as tool error results, never fabricated content."""

from __future__ import annotations

from typing import Any

import httpx

from src.errors import EngineError
from src.settings import RetryCfg

# Same transient set the session layer uses (CLAUDE.md §8 Phase 5).
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})


class ConnectorError(EngineError):
    """A profile connector (academic API, search fallback, page capture)
    failed: unreachable endpoint, missing dependency, bad payload."""


async def http_get_with_retry(
    url: str,
    *,
    retry_cfg: RetryCfg,
    timeout: float,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET with exponential backoff on TRANSIENT failures only: transport
    errors and 408/429/5xx/529. Permanent statuses (403/404/...) raise
    immediately — a blocked page is not a flaky page."""
    from tenacity import (
        AsyncRetrying,
        RetryError,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    class _Transient(Exception):
        pass

    async def _attempt() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout, headers=headers
            ) as client:
                response = await client.get(url, params=params)
        except httpx.TransportError as exc:
            raise _Transient(f"transport: {exc}") from exc
        if response.status_code in TRANSIENT_HTTP_STATUSES:
            raise _Transient(f"HTTP {response.status_code}")
        response.raise_for_status()  # permanent 4xx -> HTTPStatusError, no retry
        return response

    try:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_Transient),
            stop=stop_after_attempt(retry_cfg.attempts),
            wait=wait_exponential(
                multiplier=retry_cfg.base_delay_seconds, max=retry_cfg.max_delay_seconds
            ),
            reraise=False,
        ):
            with attempt:
                return await _attempt()
    except RetryError as exc:
        raise httpx.TransportError(
            f"GET {url} failed after {retry_cfg.attempts} attempts: "
            f"{exc.last_attempt.exception()}"
        ) from exc
    raise AssertionError("unreachable")  # pragma: no cover


async def http_post_with_retry(
    url: str,
    *,
    retry_cfg: RetryCfg,
    timeout: float,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST with the same transient-only backoff as the GET helper. Search APIs
    like Serper are POST + JSON body; a bad key (403) raises immediately (no point
    retrying a permanent auth failure), while 429/5xx/transport blips back off."""
    from tenacity import (
        AsyncRetrying,
        RetryError,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    class _Transient(Exception):
        pass

    async def _attempt() -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout, headers=headers
            ) as client:
                response = await client.post(url, json=json_body)
        except httpx.TransportError as exc:
            raise _Transient(f"transport: {exc}") from exc
        if response.status_code in TRANSIENT_HTTP_STATUSES:
            raise _Transient(f"HTTP {response.status_code}")
        response.raise_for_status()  # permanent 4xx (e.g. 403 bad key) -> no retry
        return response

    try:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_Transient),
            stop=stop_after_attempt(retry_cfg.attempts),
            wait=wait_exponential(
                multiplier=retry_cfg.base_delay_seconds, max=retry_cfg.max_delay_seconds
            ),
            reraise=False,
        ):
            with attempt:
                return await _attempt()
    except RetryError as exc:
        raise httpx.TransportError(
            f"POST {url} failed after {retry_cfg.attempts} attempts: "
            f"{exc.last_attempt.exception()}"
        ) from exc
    raise AssertionError("unreachable")  # pragma: no cover
