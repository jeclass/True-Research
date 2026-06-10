"""General-purpose research profile (CLAUDE.md §7): web search + readers;
rubric weights breadth, source diversity, recency."""

from __future__ import annotations

from typing import Any

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset


class GeneralProfile(Profile):
    name = "general"

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        return self._base_toolset(ctx)

    def url_preferences(self) -> dict[str, Any]:
        # Authority-first selection: when primary/institutional pages appear
        # in results, read them before blogs and aggregators (observed smoke8
        # 2026-06-10: judge scored source_quality 5/10 — headline figures from
        # one vendor echoed by SEO blogs).
        return {
            "preferred_domains": [
                "gov",
                "edu",
                "ac.uk",
                "europa.eu",
                "who.int",
                "oecd.org",
                "ieee.org",
                "nature.com",
            ],
            "domain_cap_overrides": {},
        }

    def rubric(self) -> str:
        return """\
- Breadth: the findings must cover the question's major facets, not one angle.
- Source diversity: conclusions resting on a single outlet, author, or
  interest group FAIL. Demand at least two independent origins for every
  load-bearing claim.
- Recency: for anything time-sensitive, the sources must be recent enough
  that the conclusion still holds; flag stale evidence explicitly.
- Credibility: weigh the registered credibility scores — a conclusion carried
  by sub-50 sources is not conclusive."""

    def worker_guidance(self) -> str:
        return """\
- Prefer primary and authoritative sources over aggregators and SEO content.
  Named source types to target with queries: government/regulator data and
  reports (site:gov), academic studies and reviews (site:edu, journals),
  manufacturer/vendor primary documentation and specs, standards bodies and
  industry associations. Pair each topical query with at least one variant
  aimed at these (e.g. append "study", "report", "site:gov", or a known
  agency/publisher name).
- Deliberately seek at least two INDEPENDENT sources for load-bearing claims
  (different publishers, not two articles citing the same wire story, and
  not multiple blogs echoing one vendor's dataset).
- Note publication dates in source notes; prefer the most recent solid
  evidence for time-sensitive questions."""
