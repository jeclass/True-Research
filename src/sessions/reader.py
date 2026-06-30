"""Reader fan-out (CLAUDE.md §1/§6, Phase 3): one cheap session per source.

The ENGINE fetches the page (httpx) and hands extracted text to a reader
session with NO tools — the reader only summarizes, grades credibility, and
returns structure. This keeps the high-volume role free of tool-calling
(where local models are weakest) and routable to any endpoint per config:
point the reader_subagent role at `local` for zero-marginal-cost reads.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import untrusted
from src.sessions.base import ReaderError, Spawn, run_role_session_async
from src.settings import Settings

_ROLE = "reader_subagent"

_SYSTEM_PROMPT = """\
You are a READER for a research engine. You receive the extracted text of ONE
web page plus the research question it was fetched for. You have no tools.

Produce:
- useful: false if the page is irrelevant, paywalled-empty, an error page, or
  otherwise contains nothing that helps the question. Never fabricate.
- title: the page/document's real title.
- kind: "paper" for journal articles/preprints/systematic reviews, "web"
  otherwise.
- credibility 0-100: 90+ peer-reviewed/primary data; 70-89 major
  institutions/quality press; 40-69 expert blogs/industry; <40 weak.
- notes: one line — venue, year, study type, access limits.
- summary_markdown: the facts from THIS page that bear on the question —
  numbers, effect sizes, sample sizes, conclusions, caveats — compressed and
  faithful. Quote key figures exactly. No filler, no outside knowledge.
- key_quotes: 0-3 short sentences COPIED CHARACTER-FOR-CHARACTER from the page
  text — the exact wording backing the most load-bearing fact in your summary
  (a key number, a conclusion, a caveat). These become the report's checkable
  citation anchor, so they MUST be a verbatim substring of the page text, not a
  paraphrase. The engine discards any quote that isn't an exact match — leave
  key_quotes empty rather than approximate one."""

# The page text is UNTRUSTED web content — append the injection-defense clause so
# the reader treats it as data, never instructions (roadmap hardening 2026-06-30).
_SYSTEM_PROMPT = _SYSTEM_PROMPT + "\n\n" + untrusted.INJECTION_DEFENSE_CLAUSE


class ReaderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    useful: bool
    title: str
    kind: Literal["web", "paper", "page_capture"]
    credibility: int
    notes: str
    summary_markdown: str
    # Span-level citation anchors (roadmap). Verified verbatim against the page
    # text in read_source — see _verify_quotes — so a non-empty entry here is a
    # genuine quote, never a model paraphrase.
    key_quotes: list[str] = []


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._chunks))


def extract_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def _finalize_text(body: str, content_type: str, url: str, settings: Settings) -> str:
    text = extract_text(body) if "html" in content_type else body
    if not text.strip():
        raise ReaderError(f"no extractable text at {url} (content-type {content_type})")
    limit = settings.reader.max_page_chars
    if len(text) > limit:
        # HEAD + TAIL, not head-only (root-cause fix 2026-06-29). Plain text[:limit]
        # dropped the entire back half of long papers, so a methods/dosing block or
        # a results/comparator table sitting past the cut vanished — and the reader,
        # unable to see what was removed, manufactured false "X is absent / no data"
        # claims (the rosemary-NMA, saw-palmetto-dose, and procyanidin errors were
        # all this). Keep the front (abstract/intro/methods/early-results) AND the
        # tail (discussion/conclusions/late tables/references), eliding only the
        # deep middle, with a visible marker so the reader knows a gap exists.
        head = int(limit * 0.75)
        tail = limit - head
        elided = len(text) - limit
        text = (
            text[:head]
            + f"\n\n[... {elided} chars elided from the MIDDLE of this document by "
            "the engine; the head and tail are preserved. If a specific table, dose, "
            "or comparator might lie in the elided middle, treat its absence here as "
            "UNKNOWN, not as evidence of absence ...]\n\n"
            + text[-tail:]
        )
    return text


async def _fetch_via_httpx(url: str, settings: Settings) -> str:
    from src.tools import http_get_with_retry

    try:
        response = await http_get_with_retry(
            url,
            retry_cfg=settings.retry,
            timeout=settings.reader.fetch_timeout_seconds,
            headers={"User-Agent": "marathon-research-engine/0.1 (+research)"},
        )
    except httpx.HTTPError as exc:
        raise ReaderError(f"fetch failed for {url}: {exc}") from exc
    content_type = response.headers.get("content-type", "")
    try:
        text = response.text
    except Exception as exc:  # noqa: BLE001 — a bogus Content-Encoding/charset
        # (observed 2026-06-24: a server declaring `Content-Encoding: base64`)
        # makes httpx's decoder raise NON-HTTPError types (AssertionError,
        # LookupError, UnicodeDecodeError). Treat an undecodable body as a failed
        # read so the run degrades (stealth retry -> skip), never crashes.
        raise ReaderError(f"fetch failed for {url}: undecodable response ({exc!r})") from exc
    return _finalize_text(text, content_type, url, settings)


def _stealth_fetch_sync(url: str, timeout_seconds: float) -> str:
    """Scrapling StealthyFetcher (browser-rendered, anti-bot). Sync — run via
    asyncio.to_thread. Import is lazy so the engine runs without the optional
    dependency."""
    from scrapling.fetchers import StealthyFetcher

    # network_idle lets client-rendered pages finish loading (the common
    # tier-1 failure: JS-only sites that return an empty shell to httpx).
    # Enterprise-captcha walls (e.g. PubMed reCAPTCHA) stay unrescuable — the
    # scientific profile routes around them to PMC/Europe-PMC mirrors.
    page = StealthyFetcher.fetch(
        url, headless=True, network_idle=True, timeout=int(timeout_seconds * 1000)
    )
    status = getattr(page, "status", 200)
    if status >= 400:
        raise ReaderError(f"stealth fetch for {url} returned HTTP {status}")
    body = getattr(page, "html_content", None) or getattr(page, "body", "") or ""
    if not isinstance(body, str):
        body = body.decode("utf-8", errors="replace")
    return body


def _stealth_available() -> bool:
    try:
        import scrapling.fetchers  # noqa: F401
        return True
    except Exception:
        return False


async def fetch_page(url: str, settings: Settings) -> str:
    """Fetch one URL and return extracted text, truncated to the configured
    budget. Tier 1 is plain httpx (1-5s). On ANY tier-1 failure — bot-walls
    (403/406/429), JS-only pages with no extractable text, timeouts — tier 2
    makes ONE Scrapling stealth-browser attempt when reader.stealth_fallback
    is enabled (2026-06-11: ~5-7 of 12 selected reads were failing on exactly
    these). If both tiers fail, the ORIGINAL error surfaces. Raises
    ReaderError on any fetch problem — callers surface it to the worker as a
    failed read, never as fabricated content."""
    import asyncio

    try:
        return await _fetch_via_httpx(url, settings)
    except ReaderError as primary:
        if not settings.reader.stealth_fallback or not _stealth_available():
            raise
        try:
            stealth_timeout = max(settings.reader.fetch_timeout_seconds, 30)
            body = await asyncio.to_thread(_stealth_fetch_sync, url, stealth_timeout)
            return _finalize_text(body, "text/html", url, settings)
        except ReaderError:
            raise primary  # stealth was best-effort; report the real failure
        except Exception as exc:  # browser/driver faults must not crash a run
            raise ReaderError(
                f"fetch failed for {url}: {primary} (stealth fallback also "
                f"failed: {type(exc).__name__}: {exc})"
            ) from primary


def _normalize_for_match(text: str) -> str:
    """Collapse whitespace runs so HTML-extraction whitespace noise (newlines,
    repeated spaces) doesn't falsely reject a genuinely verbatim quote."""
    return re.sub(r"\s+", " ", text).strip()


def _verify_quotes(quotes: list[str], page_text: str) -> list[str]:
    """Keep only key_quotes that are an exact (whitespace-normalized) substring of
    the page text. This is the trust property that makes a quote a real citation
    anchor rather than more potentially-hallucinated text: a non-empty result here
    is GENUINELY verbatim, never a model paraphrase. Silently filtered, not raised
    — this is best-effort enrichment, not an invariant on the read itself (the
    summary_markdown / credibility / traceability checks already gate the read)."""
    haystack = _normalize_for_match(page_text)
    verified = []
    for q in quotes:
        norm = _normalize_for_match(q)
        if norm and norm in haystack:
            verified.append(q.strip())
    return verified


async def read_source(
    *,
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    url: str,
    question: str,
    why: str,
) -> tuple[ReaderOutput, Spawn]:
    """Fetch one URL and run one reader session over it. The spawn is
    ledgered by the session layer (endpoint-attributed; usd=0 on local)."""
    page_text = await fetch_page(url, settings)
    # The page text AND the search snippet (`why`) are untrusted fetched content —
    # fence them so the reader treats them as data, not instructions (roadmap
    # injection defense). The question/URL are engine-owned and stay unfenced.
    user_prompt = (
        f"# Research question this page was fetched for\n{question}\n\n"
        f"# Why the worker wants this page (from a search snippet — untrusted)\n"
        f"{untrusted.wrap_untrusted(why, label='search snippet')}\n\n"
        f"# Page URL\n{url}\n\n"
        f"# Extracted page text (untrusted)\n"
        f"{untrusted.wrap_untrusted(page_text, label='page text')}\n"
    )
    spawn = await run_role_session_async(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="reader",
        role=_ROLE,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=[],
        output_model=ReaderOutput,
    )
    output: ReaderOutput = spawn.structured
    if not 0 <= output.credibility <= 100:
        raise ReaderError(f"reader returned credibility {output.credibility} outside 0-100")
    if output.key_quotes:
        output = output.model_copy(
            update={"key_quotes": _verify_quotes(output.key_quotes, page_text)}
        )
    return output, spawn
