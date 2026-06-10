"""Page capture + vision analysis for the visual profile (CLAUDE.md §7).

The engine captures a full-page screenshot with Playwright into
runs/<id>/captures/, then spawns a VISION reader session (role
`vision_reader`, must be a vision-capable model) that Reads the image and
returns the same structured ReaderOutput shape as text readers — so captured
pages flow through the identical source-registration and read-gate machinery
with kind=page_capture."""

from __future__ import annotations

import re
from pathlib import Path

from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions.base import ReaderError, Spawn, run_role_session_async
from src.sessions.reader import ReaderOutput
from src.settings import Settings
from src.tools import ConnectorError

CAPTURES_DIR = "captures"
_VIEWPORT = {"width": 1280, "height": 2400}

_VISION_SYSTEM_PROMPT = """\
You are a VISION READER for a research engine. You receive a full-page
screenshot of ONE web page (use the Read tool on the path you are given to
view it) plus the research question it was captured for.

Analyze what is VISIBLE — layout and conversion psychology, not the prose:
- overall layout structure and visual hierarchy (hero, sections, grids)
- claim density: how many distinct marketing/feature claims are visible
- badges, certifications, awards, star ratings, review counts and WHERE they
  sit on the page (social proof placement)
- imagery style: lifestyle photography vs white-background product shots vs
  illustration — estimate the ratio
- pricing/CTA prominence, urgency/scarcity devices
- anything notable or unusual about the visual presentation

Produce (JSON schema enforced):
- useful: false if the capture is an error page, cookie-wall, or blank.
- title: the page's visible title/brand.
- kind: ALWAYS "page_capture".
- credibility 0-100: how authoritative this page is AS A PRIMARY VISUAL
  ARTIFACT of the brand/listing itself (a brand's own page is a primary
  source about that brand's presentation: usually 75+).
- notes: one line — what page this is and capture quality.
- summary_markdown: the visual-pattern observations above, concrete and
  countable (e.g. "3 trust badges directly under the CTA"). Never invent
  elements you cannot see."""


def _slugify(url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")
    return slug[:80] or "capture"


async def capture_page(url: str, run: Runspace, settings: Settings) -> str:
    """Screenshot one URL; returns the capture's path relative to the run dir.
    Raises ConnectorError on missing Playwright/browser or navigation failure."""
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ConnectorError(
            "the visual profile needs Playwright: pip install playwright && "
            "playwright install chromium"
        ) from exc

    captures = run.root / CAPTURES_DIR
    captures.mkdir(exist_ok=True)
    existing = len(list(captures.glob("*.png")))
    relpath = f"{CAPTURES_DIR}/{existing + 1:03d}-{_slugify(url)}.png"
    timeout_ms = int(settings.reader.fetch_timeout_seconds * 1000)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page(viewport=_VIEWPORT)
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)  # settle lazy-loaded heroes
                image = await page.screenshot(full_page=True, type="png")
            finally:
                await browser.close()
    except PlaywrightError as exc:
        raise ConnectorError(f"page capture failed for {url}: {exc}") from exc

    (run.root / relpath).write_bytes(image)
    return relpath


async def analyze_capture(
    *,
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    relpath: str,
    url: str,
    question: str,
    why: str,
) -> tuple[ReaderOutput, Spawn]:
    """One vision session over one capture. Ledgered like any reader."""
    user_prompt = (
        f"# Research question this page was captured for\n{question}\n\n"
        f"# Why the worker wants this page\n{why}\n\n"
        f"# Page URL\n{url}\n\n"
        f"# Screenshot file (Read this path to view it)\n{relpath}\n"
    )
    spawn = await run_role_session_async(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="reader",
        role="vision_reader",
        system_prompt=_VISION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=["Read"],
        output_model=ReaderOutput,
    )
    output: ReaderOutput = spawn.structured
    if not 0 <= output.credibility <= 100:
        raise ReaderError(
            f"vision reader returned credibility {output.credibility} outside 0-100"
        )
    return output, spawn
