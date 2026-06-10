"""Scientific / clinical-evidence profile (CLAUDE.md §7): academic search
connectors + an evidence-grading rubric that penalizes non-primary sources.
This is the profile The Clinical Index work uses."""

from __future__ import annotations

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset
from src.tools.academic import build_academic_mcp


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
- In every finding, record study type, n, effect size (with CI/p-value when
  reported), and year for each load-bearing claim.
- In source notes record: venue, year, study type, peer-review status
  (mark preprints), and any funding conflicts you can see.
- kind="paper" for journal articles and preprints."""
