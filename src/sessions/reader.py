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
  faithful. Quote key figures exactly. No filler, no outside knowledge."""


class ReaderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    useful: bool
    title: str
    kind: Literal["web", "paper", "page_capture"]
    credibility: int
    notes: str
    summary_markdown: str


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


async def fetch_page(url: str, settings: Settings) -> str:
    """Fetch one URL and return extracted text, truncated to the configured
    budget. Raises ReaderError on any fetch problem — callers surface it to
    the worker as a failed read, never as fabricated content."""
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
    body = response.text
    text = extract_text(body) if "html" in content_type else body
    if not text.strip():
        raise ReaderError(f"no extractable text at {url} (content-type {content_type})")
    limit = settings.reader.max_page_chars
    if len(text) > limit:
        text = text[:limit] + "\n\n[TRUNCATED by engine at page-char budget]"
    return text


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
    user_prompt = (
        f"# Research question this page was fetched for\n{question}\n\n"
        f"# Why the worker wants this page\n{why}\n\n"
        f"# Page URL\n{url}\n\n"
        f"# Extracted page text\n{page_text}\n"
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
    return output, spawn
