"""Community lens (docs/COMMUNITY_LENS_SPEC.md): surfaces first-hand, lived
experience from forums and Q&A sites as a SEPARATE evidence class.

Quarantine is the whole point. Community findings live on the `community`
track, never enter the factual synthesizer's context, and land in their own
clearly-framed report section. The reader's own credibility rubric already
scores forum content low (<40) — this lens keeps it useful by judging it on
coverage of real voices rather than authority, and by never letting it back
a factual claim.
"""

from __future__ import annotations

from typing import Any

from src.errors import ConfigError
from src.lenses import Lens, register
from src.settings import Settings

# General web search scoped to community/UGC hosts. Using site-filters (rather
# than SearXNG engine bangs) keeps this working against the default engine set
# with no container reconfiguration.
_COMMUNITY_SITES = (
    "reddit.com",
    "news.ycombinator.com",
    "stackexchange.com",
    "quora.com",
)
_SITE_FILTER = "(" + " OR ".join(f"site:{s}" for s in _COMMUNITY_SITES) + ")"


@register
class CommunityLens(Lens):
    name = "community"

    def track(self) -> str:
        return "community"

    def search_providers(self, settings: Settings) -> list[tuple[str, Any]]:
        base_url = settings.search.searxng_base_url
        if not base_url:
            raise ConfigError(
                "community lens needs search.searxng_base_url for forum search"
            )
        from src.tools.search import searxng_results

        max_results = settings.search.max_results
        timeout = settings.reader.fetch_timeout_seconds
        retry = settings.retry

        async def _community(query: str):
            scoped = f"{query} {_SITE_FILTER}"
            return await searxng_results(base_url, scoped, max_results, timeout, retry)

        return [("community", _community)]

    def seed_questions(self, main_question: str) -> list[tuple[str, int]]:
        return [
            (
                "What do people with direct, first-hand experience report about "
                f"the following, in community discussions (Reddit, forums, Q&A "
                f"sites): {main_question}? Capture recurring experiences, "
                "practical caveats, and points of disagreement — attribute each "
                "to the thread it came from.",
                3,
            ),
        ]

    def report_section_title(self) -> str:
        return "Community & practitioner perspective"

    def report_section_framing(self) -> str:
        return (
            "_The following reflects qualitative, first-hand experience shared "
            "in public community discussions. It is sentiment and anecdote — "
            "self-selected, unverified, and not representative — presented "
            "separately from, and never as a substitute for, the evidence-based "
            "findings above. Treat it as 'what people report experiencing', not "
            "as established fact._"
        )
