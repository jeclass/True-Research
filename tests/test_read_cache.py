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
        claim = cache.claim("https://x.org/a")
        if claim.owner:
            try:
                result = await expensive_read()
                claim.resolve(result)
            except Exception as exc:  # pragma: no cover - defensive
                claim.fail(exc)
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


def test_url_normalization_applies_to_cache_keys():
    cache = _cache()
    cache.store_completed("https://x.org/page/", "OUT", origin="q-001")
    assert cache.get_completed("https://x.org/page") is not None


def test_for_run_returns_same_cache_for_same_root(tmp_path):
    a = read_cache.for_run(tmp_path / "run1")
    b = read_cache.for_run(tmp_path / "run1")
    c = read_cache.for_run(tmp_path / "run2")
    assert a is b and a is not c
