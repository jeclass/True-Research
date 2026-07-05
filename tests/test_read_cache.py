"""Per-run read cache (spec 2026-07-05 §2.1/§3.2): completed-output reuse,
in-flight coalescing within one loop, content-hash duplicate detection.
Hermetic — no network, no SDK."""

import asyncio

import pytest

from src.sessions import read_cache


def _cache():
    return read_cache.RunReadCache()


def test_completed_output_is_returned_on_second_lookup():
    cache = _cache()

    async def scenario():
        assert cache.get_completed("https://x.org/a") is None
        cache.store_completed("https://x.org/a", "OUTPUT-A", origin="q-001")
        hit = cache.get_completed("https://x.org/a")
        assert hit is not None
        assert hit.output == "OUTPUT-A" and hit.origin == "q-001"

    asyncio.run(scenario())


def test_inflight_coalescing_single_fetch_for_concurrent_callers():
    cache = _cache()
    calls = {"n": 0}

    async def expensive_read():
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return f"RESULT-{calls['n']}"

    async def caller():
        # Canonical consumer pattern: the OWNER must settle in ALL paths,
        # including cancellation — hence BaseException, fail, re-raise.
        claim = cache.claim("https://x.org/a")
        if claim.owner:
            try:
                result = await expensive_read()
            except BaseException as exc:  # pragma: no cover - defensive
                claim.fail(exc)
                raise
            claim.resolve(result)
            return result
        return await claim.wait()

    async def scenario():
        results = await asyncio.gather(*(caller() for _ in range(5)))
        return results

    results = asyncio.run(scenario())
    assert calls["n"] == 1                       # exactly one real fetch
    assert set(results) == {"RESULT-1"}          # everyone got the winner's result


def test_failed_inflight_is_not_cached_and_next_caller_retries():
    cache = _cache()

    async def scenario():
        claim = cache.claim("https://x.org/a")
        assert claim.owner
        claim.fail(RuntimeError("fetch died"))
        # in-flight entry must be gone; a fresh claim gets ownership again
        claim2 = cache.claim("https://x.org/a")
        assert claim2.owner
        claim2.resolve("OK")
        return True

    assert asyncio.run(scenario())
    # failure was never stored as a completed result
    assert cache.get_completed("https://x.org/a") is None


def test_waiter_receives_owner_exception_on_fail():
    cache = _cache()

    async def scenario():
        claim = cache.claim("https://x.org/a")
        assert claim.owner

        async def waiter():
            c = cache.claim("https://x.org/a")
            assert not c.owner
            return await c.wait()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0)  # let the waiter attach to the shared future
        claim.fail(RuntimeError("fetch died"))
        with pytest.raises(RuntimeError, match="fetch died"):
            await waiter_task
        # and the next claimer re-owns (no stale entry)
        claim2 = cache.claim("https://x.org/a")
        assert claim2.owner
        claim2.resolve("OK")

    asyncio.run(scenario())


def test_waiter_cancellation_does_not_poison_sibling_waiters():
    cache = _cache()

    async def scenario():
        release = asyncio.Event()
        claim = cache.claim("https://x.org/a")
        assert claim.owner

        async def owner():
            await release.wait()
            claim.resolve("WINNER")

        async def waiter():
            c = cache.claim("https://x.org/a")
            assert not c.owner
            return await c.wait()

        owner_task = asyncio.create_task(owner())
        waiter_a = asyncio.create_task(waiter())
        waiter_b = asyncio.create_task(waiter())
        await asyncio.sleep(0)  # both waiters attach to the ONE shared future
        waiter_a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_a
        release.set()
        # A's cancellation (e.g. a per-question timeout) must not cancel the
        # shared future out from under innocent sibling B.
        assert await waiter_b == "WINNER"
        await owner_task

    asyncio.run(scenario())


def test_owner_cancellation_releases_waiters_and_next_claim_reowns():
    cache = _cache()

    async def scenario():
        owner_started = asyncio.Event()

        async def owner():
            claim = cache.claim("https://x.org/a")
            assert claim.owner
            owner_started.set()
            try:
                await asyncio.Event().wait()  # a fetch that never finishes
            except BaseException as exc:  # owner contract: settle in ALL paths
                claim.fail(exc)
                raise

        owner_task = asyncio.create_task(owner())
        await owner_started.wait()

        async def waiter():
            c = cache.claim("https://x.org/a")
            assert not c.owner
            return await c.wait()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0)  # waiter attaches
        owner_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner_task
        # waiter is released promptly (no hang until loop teardown)…
        with pytest.raises(asyncio.CancelledError):
            await waiter_task
        # …and the abandoned entry is gone: a fresh claim re-owns immediately
        claim2 = cache.claim("https://x.org/a")
        assert claim2.owner
        claim2.resolve("OK")

    asyncio.run(scenario())


def test_inflight_table_resets_across_event_loops():
    cache = _cache()

    async def first_loop():
        claim = cache.claim("https://x.org/a")
        assert claim.owner
        # deliberately never resolve — simulates a loop torn down mid-flight

    async def second_loop():
        claim = cache.claim("https://x.org/a")
        return claim.owner

    asyncio.run(first_loop())
    # a NEW loop must not await a dead loop's future: ownership is re-granted
    assert asyncio.run(second_loop()) is True


def test_content_hash_first_url_wins_and_duplicate_is_reported():
    cache = _cache()
    text = "Same   body\nwith whitespace noise"
    first = cache.note_content("https://a.org/story", text)
    assert first is None                          # first sighting: no duplicate
    dup = cache.note_content("https://b.mirror.net/story", "Same body with whitespace noise")
    assert dup == "https://a.org/story"           # whitespace-normalized match
    # same URL re-noting its own content is NOT a duplicate
    assert cache.note_content("https://a.org/story", text) is None


def test_note_content_ignores_empty_text():
    cache = _cache()
    # an empty page must not become the canonical "first URL"…
    assert cache.note_content("https://a.org/empty", "   \n\t") is None
    # …that every later empty fetch reports as its duplicate
    assert cache.note_content("https://b.org/empty", "") is None


def test_url_normalization_applies_to_cache_keys():
    cache = _cache()
    cache.store_completed("https://x.org/page/", "OUT", origin="q-001")
    assert cache.get_completed("https://x.org/page") is not None


def test_for_run_returns_same_cache_for_same_root(tmp_path):
    a = read_cache.for_run(tmp_path / "run1")
    b = read_cache.for_run(tmp_path / "run1")
    c = read_cache.for_run(tmp_path / "run2")
    assert a is b and a is not c


# ---------- integration with reader.read_source ----------

from src.sessions import reader as reader_mod
from src.sessions.base import Spawn


class _FakeRun:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.progress_lines: list[str] = []
        self.decisions: list[str] = []

    def log(self, text):
        self.progress_lines.append(text)

    def log_decision(self, text):
        self.decisions.append(text)


def _fake_spawn(structured):
    return Spawn(structured=structured, result_text="", input_tokens=1,
                 output_tokens=1, cached_tokens=0, usd=0.0, wall_seconds=0.1,
                 num_turns=1)


def _reader_output(useful=True, notes="ok"):
    return reader_mod.ReaderOutput(
        title="T", kind="web", credibility=70, useful=useful,
        notes=notes, summary_markdown="body", key_quotes=[],
    )


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    run = _FakeRun(tmp_path / "runA")
    fetches = {"n": 0}
    sessions = {"n": 0}

    async def fake_fetch(url, settings):
        fetches["n"] += 1
        return f"PAGE TEXT for {url}"

    async def fake_session(**kwargs):
        sessions["n"] += 1
        return _fake_spawn(_reader_output())

    monkeypatch.setattr(reader_mod, "fetch_page", fake_fetch)
    monkeypatch.setattr(reader_mod, "run_role_session_async", fake_session)
    read_cache._CACHES.clear()
    return run, fetches, sessions


def _read(run, url, question="q?"):
    return asyncio.run(reader_mod.read_source(
        run=run, settings=None, ledger=None, cycle=1,
        url=url, question=question, why="",
    ))


def test_read_source_second_call_same_url_hits_cache(wired):
    run, fetches, sessions = wired
    out1, _ = _read(run, "https://x.org/a")
    out2, spawn2 = _read(run, "https://x.org/a")
    assert fetches["n"] == 1 and sessions["n"] == 1     # one fetch, one session
    assert out2.summary_markdown == out1.summary_markdown
    assert spawn2 is None                                # no new spend
    assert any("cache" in ln.lower() for ln in run.progress_lines)


def test_read_source_duplicate_content_different_url_soft_skips(wired, monkeypatch):
    run, fetches, sessions = wired

    async def same_text_fetch(url, settings):
        fetches["n"] += 1
        return "IDENTICAL SYNDICATED BODY"

    monkeypatch.setattr(reader_mod, "fetch_page", same_text_fetch)
    out1, _ = _read(run, "https://a.org/story")
    out2, spawn2 = _read(run, "https://b.mirror.net/story")
    assert sessions["n"] == 1                            # second never spawned a session
    assert out2.useful is False                          # soft: flows as not-useful
    assert "a.org" in out2.notes                         # names the first URL
    assert spawn2 is None
    assert any("duplicate content" in d.lower() for d in run.decisions)  # logged DECISION


def test_read_source_fetch_failure_is_not_cached(wired, monkeypatch):
    run, fetches, sessions = wired
    attempts = {"n": 0}

    async def flaky_fetch(url, settings):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise reader_mod.ReaderError("boom")
        return "PAGE TEXT"

    monkeypatch.setattr(reader_mod, "fetch_page", flaky_fetch)
    with pytest.raises(reader_mod.ReaderError):
        _read(run, "https://x.org/a")
    out, _ = _read(run, "https://x.org/a")               # retry succeeds
    assert attempts["n"] == 2 and out.useful is True
