"""General-purpose research profile (CLAUDE.md §7): web search + readers;
rubric weights breadth, source diversity, recency."""

from __future__ import annotations

from typing import Any

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset
from src.settings import Settings


class GeneralProfile(Profile):
    name = "general"

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        return self._base_toolset(ctx)

    def pipeline_search_providers(self, settings: Settings) -> list[tuple[str, Any]]:
        # Depth+breadth stack, all merged by the pipeline:
        #   - OpenAlex: the scholarly index, so general research reaches journal
        #     papers web crawlers can't surface (a trial's PRIMARY publication).
        #     Free, no-key, no-Docker; carries title+abstract even when paywalled.
        #   - Web: Serper (Google) when SERPER_API_KEY is present — Google's broad
        #     index, cheap enough that breadth comes from MANY queries, deep-read by
        #     the engine's own reader. On any Serper failure/quota-exhaustion it
        #     falls back to a configured SearXNG (if one is set), then to DDG, so a
        #     bad key / outage never kills a run. Without a Serper key, the web slot
        #     is the base SearXNG -> DDG provider (the self-host path).
        # Portable: a GitHub clone runs the same with the user's own key, no Docker.
        from src.tools.academic import openalex_results

        max_results = settings.search.max_results
        timeout = settings.reader.fetch_timeout_seconds

        async def _openalex(query: str):
            return await openalex_results(query, max_results, timeout, settings.retry)

        sc = settings.search
        serper_key = (
            settings.secrets.get(sc.serper_api_key_env) if sc.serper_api_key_env else None
        )
        if serper_key:
            from src.tools import ConnectorError
            from src.tools.search import ddg_results, searxng_results, serper_results

            key = serper_key.get_secret_value()

            async def _web(query: str):
                try:
                    results = await serper_results(
                        key, query, max_results, timeout, settings.retry,
                        endpoint=sc.serper_endpoint, gl=sc.serper_gl, hl=sc.serper_hl,
                    )
                    if results:
                        return results
                    # Serper up but no hits — fall through to the next tier.
                except ConnectorError:
                    pass  # Serper down / quota / bad key -> next tier so research survives
                # A configured, healthy SearXNG is a better fallback than DDG's
                # narrower index, so consult it BEFORE DDG when both are available
                # (matches preflight's Serper -> SearXNG -> DDG order; audit #5).
                # An operator running hybrid (Serper key + local SearXNG safety net)
                # who exhausts Serper's free quota mid-run now gets their full index,
                # not a silent degrade straight to DDG. Skipped when no SearXNG is
                # configured (the common portable case), leaving Serper -> DDG.
                if sc.searxng_base_url:
                    try:
                        results = await searxng_results(
                            sc.searxng_base_url, query, max_results, timeout, settings.retry
                        )
                        if results:
                            return results
                    except ConnectorError:
                        pass  # SearXNG down too -> DDG
                return await ddg_results(query, max_results, timeout)

            web_providers = [("serper", _web)]
        else:
            web_providers = super().pipeline_search_providers(settings)  # searxng -> ddg

        return [("openalex", _openalex)] + web_providers

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
  by sub-50 sources is not conclusive.
- Negative claims: any "X is absent / not reported / no data exists" assertion
  must be AFFIRMATIVELY grounded in a fully-read source. An unsupported negative —
  especially one that could stem from a truncated read missing a table or methods
  block — is a FAIL: send it back to be re-checked against the full source, or
  require it softened to "not found among the sources reviewed.\""""

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
- Specific numbers — doses, sample sizes, concentrations, effect sizes,
  endpoints — must come from the PRIMARY study (the trial/meta-analysis itself),
  NOT a blog's or aggregator's restatement. When two sources disagree on a number,
  go to the primary to settle it rather than picking the convenient figure.
- Do NOT record an absence ("no data on X", "X not studied", "not in the table")
  from a source you read only partially. A negative finding requires a FULL read
  of the source that would contain it; otherwise report "not found in sources read
  so far" and keep the question open.
- Note publication dates in source notes; prefer the most recent solid
  evidence for time-sensitive questions."""
