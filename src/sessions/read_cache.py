"""Per-run read cache (spec 2026-07-05 §2.1/§3.2).

Three concerns, one per-run object:
  1. COMPLETED outputs — plain data keyed by normalized URL, safe to reuse
     across cycles/event loops. A cache hit skips fetch + reader session.
  2. IN-FLIGHT coalescing — concurrent callers for the same URL (parallel
     questions, parallel tool calls in one worker message) share ONE fetch.
     Futures are loop-bound, so the in-flight table is discarded whenever the
     running loop changes (each driver-called session runs its own loop).
  3. CONTENT HASHES (§3.2) — whitespace-normalized sha256 of fetched text;
     lets the reader layer detect that a *different* URL carries identical
     content (syndication mirrors) BEFORE spending a reader session.

CONCURRENCY NOTE (load-bearing): claim()/get_completed()/note_content() do no
awaiting — in asyncio's single-threaded model, a synchronous check-and-insert
is atomic w.r.t. other coroutines, so no Lock is needed. Do not add an await
inside claim() without re-introducing a lock.

Failures are never cached: a claim that fails is removed so later callers
retry fresh (a transient fetch error must not poison the URL for the run).
Cache lifetime is the driver process (one run per process); for_run() keys by
run root so tests with multiple tmp runspaces stay isolated.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.sessions import common


@dataclass(frozen=True)
class CompletedRead:
    output: Any          # ReaderOutput (typed Any to keep this module import-light)
    origin: str          # question id (or label) that first triggered the read


class _Claim:
    """Result of claim(): either you're the owner (do the real work, then
    resolve()/fail()), or you wait() on the owner's future."""

    def __init__(self, owner: bool, future: asyncio.Future, cache: "RunReadCache", key: str):
        self.owner = owner
        self._future = future
        self._cache = cache
        self._key = key

    async def wait(self):
        return await self._future

    def resolve(self, value: Any) -> None:
        if not self._future.done():
            self._future.set_result(value)
        self._cache._inflight.pop(self._key, None)

    def fail(self, exc: BaseException) -> None:
        if not self._future.done():
            self._future.set_exception(exc)
        # Retrieve to mark the exception as consumed when nobody awaits it
        # (avoids "exception was never retrieved" warnings for solo callers).
        if self._future.done() and not self._future.cancelled():
            self._future.exception()
        self._cache._inflight.pop(self._key, None)


_WS_RE = re.compile(r"\s+")


class RunReadCache:
    def __init__(self) -> None:
        self._done: dict[str, CompletedRead] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._loop_id: int | None = None
        self._content_hashes: dict[str, str] = {}  # sha256 -> first URL (normalized)

    # -- loop hygiene ---------------------------------------------------------
    def _sync_loop(self) -> None:
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:  # not in a loop (sync test helper paths)
            loop_id = None
        if loop_id != self._loop_id:
            # Futures from a previous loop are unawaitable here — drop them.
            self._inflight = {}
            self._loop_id = loop_id

    # -- completed cache ------------------------------------------------------
    def get_completed(self, url: str) -> CompletedRead | None:
        return self._done.get(common.normalize_url(url))

    def store_completed(self, url: str, output: Any, *, origin: str) -> None:
        self._done[common.normalize_url(url)] = CompletedRead(output=output, origin=origin)

    # -- in-flight coalescing ---------------------------------------------------
    def claim(self, url: str) -> _Claim:
        """Synchronous check-and-register (no awaits — see module docstring)."""
        self._sync_loop()
        key = common.normalize_url(url)
        existing = self._inflight.get(key)
        if existing is not None and not existing.done():
            return _Claim(owner=False, future=existing, cache=self, key=key)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        return _Claim(owner=True, future=future, cache=self, key=key)

    # -- content-hash dedup (§3.2) ---------------------------------------------
    def note_content(self, url: str, text: str) -> str | None:
        """Record this URL's content hash. Returns the FIRST url that carried
        identical (whitespace-normalized) content when this one is a duplicate
        of a different URL; None otherwise."""
        digest = hashlib.sha256(_WS_RE.sub(" ", text).strip().encode("utf-8")).hexdigest()
        norm = common.normalize_url(url)
        first = self._content_hashes.get(digest)
        if first is None:
            self._content_hashes[digest] = norm
            return None
        return None if first == norm else first


_CACHES: dict[str, RunReadCache] = {}


def for_run(run_root: Path) -> RunReadCache:
    """One cache per run directory (one run per driver process in practice;
    keying by root keeps concurrent tmp-path tests isolated)."""
    key = str(run_root)
    cache = _CACHES.get(key)
    if cache is None:
        cache = RunReadCache()
        _CACHES[key] = cache
    return cache
