"""Scientific / clinical-evidence profile (CLAUDE.md §7): academic search
connectors + an evidence-grading rubric that penalizes non-primary sources.
This is the profile The Clinical Index work uses."""

from __future__ import annotations

from typing import Any

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset
from src.settings import Settings
from src.tools.academic import build_academic_mcp, openalex_results, pubmed_results


class ScientificProfile(Profile):
    name = "scientific"

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        toolset = self._base_toolset(ctx)
        toolset.mcp_servers["academic"] = build_academic_mcp(ctx.settings)
        toolset.extra_allowed += [
            "mcp__academic__search_pubmed",
            "mcp__academic__search_openalex",
            "mcp__academic__search_arxiv",
        ]
        return toolset

    def pipeline_search_providers(self, settings: Settings) -> list[tuple[str, Any]]:
        providers = super().pipeline_search_providers(settings)
        timeout = settings.reader.fetch_timeout_seconds
        max_results = settings.search.max_results

        async def _openalex(query: str):
            return await openalex_results(query, max_results, timeout, settings.retry)

        async def _pubmed(query: str):
            return await pubmed_results(query, max_results, timeout, settings.retry)

        # Academic indexes first (worker_guidance order), web context last.
        return [("openalex", _openalex), ("pubmed", _pubmed)] + providers

    def url_preferences(self) -> dict[str, Any]:
        # Mirrors the a77ccdc prompt guidance, enforced in code: OA mirrors
        # rank first (publisher pages 403 automated readers), and the PMC
        # domain may exceed the per-domain cap since mirrors concentrate there.
        return {
            "preferred_domains": [
                "pmc.ncbi.nlm.nih.gov",
                "europepmc.org",
                "pubmed.ncbi.nlm.nih.gov",
            ],
            "domain_cap_overrides": {"pmc.ncbi.nlm.nih.gov": 4, "europepmc.org": 4},
        }

    def pipeline_overrides(self) -> dict[str, int]:
        # Denser pages + 403-mirror retries burn read attempts.
        return {"queries_per_question": 5, "max_reads": 16}

    def rubric(self) -> str:
        return """\
- Evidence grading: every load-bearing claim must state its evidence tier.
  Hierarchy: meta-analyses/systematic reviews of RCTs > individual RCTs >
  observational studies > mechanistic/animal work > expert opinion. A
  conclusion carried by low-tier evidence when higher tiers exist FAILS.
- Primary sources: findings must trace to the studies themselves (or their
  abstracts/registrations), not to press releases or secondary journalism
  ABOUT studies. Penalize non-primary sourcing hard.
- Study particulars: for key trials/meta-analyses, the findings must record
  study type, sample size (n), effect size with CI/p-value where available,
  and publication year. Missing numbers on a load-bearing claim = unmet.
- Peer-review status: preprints and non-reviewed sources must be labeled as
  such in source notes and weighed accordingly.
- Conflicts: industry-funded or single-group evidence on contested questions
  needs independent corroboration."""

    def worker_guidance(self) -> str:
        return """\
- Search the academic indexes FIRST (search_pubmed, search_openalex,
  search_arxiv) and only then general web search for context.
- Prioritize meta-analyses and systematic reviews of RCTs, then landmark
  individual RCTs. Read the primary record (abstract page, PMC full text)
  rather than journalism about it.
- Access note: publisher and PubMed abstract pages often block automated
  readers (HTTP 403). When a read fails, retry open-access copies in this
  order: PMC full text (pmc.ncbi.nlm.nih.gov/articles/PMC...), Europe PMC
  (europepmc.org/article/MED/<PMID>), then the journal's open-access page.
  Register whichever URL actually returned a read_source digest.
- In every finding, record study type, n, effect size (with CI/p-value when
  reported), and year for each load-bearing claim.
- In source notes record: venue, year, study type, peer-review status
  (mark preprints), and any funding conflicts you can see.
- kind="paper" for journal articles and preprints."""
