"""Visual research profile (CLAUDE.md §7): page capture + Claude-vision
analysis of REAL pages — hero images, listings, landing pages — not articles
about them. Powers the Amazon-image-psychology / brand-portrayal use cases.

capture_page is the visual sibling of read_source: engine captures the
screenshot, a vision session analyzes it, the capture counts as a "read" for
the read-gate, and the source registers with kind=page_capture."""

from __future__ import annotations

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset
from src.sessions import common
from src.sessions.base import SessionError
from src.tools import ConnectorError
from src.tools.capture import analyze_capture, capture_page


async def handle_capture(ctx: WorkerToolContext, args: dict) -> dict:
    """capture_page tool logic, module-level for direct unit testing."""
    url = str(args.get("url", "")).strip()
    why = str(args.get("why", "")).strip()
    if not url:
        return {"content": [{"type": "text", "text": "CAPTURE FAILED: empty url"}],
                "is_error": True}
    if ctx.stats["failures"] >= ctx.settings.reader.max_failures_per_session:
        return {
            "content": [{"type": "text", "text": (
                f"CAPTURES DISABLED: {ctx.stats['failures']} captures/reads "
                "failed this session (engine limit). Report what you have "
                "or outcome=blocked."
            )}],
            "is_error": True,
        }
    try:
        relpath = await capture_page(url, ctx.run, ctx.settings)
        output, _spawn = await analyze_capture(
            run=ctx.run,
            settings=ctx.settings,
            ledger=ctx.ledger,
            cycle=ctx.cycle,
            relpath=relpath,
            url=url,
            question=ctx.target.question,
            why=why,
        )
    except (ConnectorError, SessionError) as exc:
        ctx.stats["failures"] += 1
        return {"content": [{"type": "text", "text": f"CAPTURE FAILED: {exc}"}],
                "is_error": True}
    ctx.stats["reads"] += 1
    if not output.useful:
        return {"content": [{"type": "text",
                             "text": f"CAPTURE NOT USEFUL: {output.notes}"}]}
    ctx.read_urls.add(common.normalize_url(url))
    text = (
        f"TITLE: {output.title}\n"
        f"KIND: page_capture\n"
        f"CREDIBILITY: {output.credibility}\n"
        f"NOTES: {output.notes} (screenshot: {relpath})\n"
        f"URL: {url}\n"
        f"VISUAL ANALYSIS:\n{output.summary_markdown}"
    )
    return {"content": [{"type": "text", "text": text}]}


def build_capture_mcp(ctx: WorkerToolContext):
    from claude_agent_sdk import create_sdk_mcp_server, tool

    @tool(
        "capture_page",
        "Capture a full-page screenshot of ONE URL and get a vision analysis "
        "of its layout, claim density, badge/social-proof placement, and "
        "lifestyle-vs-white-background imagery. Returns TITLE/KIND/"
        "CREDIBILITY/NOTES plus the visual observations. Use this — not "
        "text reads — for every page whose PRESENTATION you are analyzing.",
        {"url": str, "why": str},
    )
    async def capture_page_tool(args: dict) -> dict:
        return await handle_capture(ctx, args)

    return create_sdk_mcp_server("capture", tools=[capture_page_tool])


class VisualProfile(Profile):
    name = "visual"

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        toolset = self._base_toolset(ctx)
        toolset.mcp_servers["capture"] = build_capture_mcp(ctx)
        toolset.extra_allowed += ["mcp__capture__capture_page"]
        return toolset

    def rubric(self) -> str:
        return """\
- Coverage: visual-pattern conclusions must rest on CAPTURED pages (sources
  of kind=page_capture) — aim for at least 5 distinct captured competitor/
  example pages across the run. Conclusions about imagery drawn only from
  text articles ABOUT imagery FAIL.
- Visual evidence: every claimed pattern (badge placement, claim density,
  lifestyle-vs-white-background ratio, CTA prominence) must cite specific
  captures where it is visible, with countable observations.
- Comparative structure: findings must compare across the captured set, not
  describe single pages in isolation.
- If captures repeatedly failed and the run fell back to text sources, that
  limitation must be loudly recorded — never passed off as visual evidence."""

    def worker_guidance(self) -> str:
        return """\
- Use capture_page (NOT read_source) for every page whose visual presentation
  you are analyzing — listings, hero sections, landing pages. read_source is
  only for text context (articles, docs).
- Capture multiple competitors/examples before concluding; patterns need a
  comparative base. Count what you see (badges, claims, image types) so the
  finding has countable evidence.
- Register captured pages with kind="page_capture" and cite them like any
  source."""
