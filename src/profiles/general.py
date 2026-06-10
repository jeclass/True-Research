"""General-purpose research profile (CLAUDE.md §7): web search + readers;
rubric weights breadth, source diversity, recency."""

from __future__ import annotations

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset


class GeneralProfile(Profile):
    name = "general"

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        return self._base_toolset(ctx)

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
- Deliberately seek at least two INDEPENDENT sources for load-bearing claims
  (different publishers, not two articles citing the same wire story).
- Note publication dates in source notes; prefer the most recent solid
  evidence for time-sensitive questions."""
