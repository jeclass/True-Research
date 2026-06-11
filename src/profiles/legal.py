"""Legal-research profile (CLAUDE.md §7) — FUTURE DOMAIN, v1 scaffold.

The domain axis's next member after general/scientific/visual. This is a
working starting point (primary-law-first rubric + guidance over the standard
web toolset), deliberately minimal: a future session should add proper legal
connectors (CourtListener / Caselaw Access Project / official statute
databases) as MCP search providers, the way scientific.py adds PubMed/OpenAlex.
Until then it runs on general web search with a legal rubric — usable, but not
yet authoritative for primary-source retrieval. Recorded as the documented
'legal (future)' domain in the two-axis model (docs/COMMUNITY_LENS.md)."""

from __future__ import annotations

from typing import Any

from src.profiles.base import Profile, WorkerToolContext, WorkerToolset


class LegalProfile(Profile):
    name = "legal"

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:
        # v1: standard web search + file tools. FUTURE: attach legal-database
        # MCP providers here (parallel to ScientificProfile.worker_toolset).
        return self._base_toolset(ctx)

    def url_preferences(self) -> dict[str, Any]:
        # Official/primary-law domains first; commentary and aggregators after.
        return {
            "preferred_domains": [
                "gov",
                "courtlistener.com",
                "supremecourt.gov",
                "legislation.gov.uk",
                "eur-lex.europa.eu",
                "law.cornell.edu",
            ],
            "domain_cap_overrides": {},
        }

    def rubric(self) -> str:
        return """\
- Primary law first: conclusions must rest on statutes, regulations, and
  decided cases — not blog posts, marketing, or secondary commentary ABOUT
  the law. A claim carried only by secondary sources is unmet.
- Jurisdiction and currency: every legal claim must state its jurisdiction and
  be checked for whether it is current (amended, repealed, overruled). Stale or
  jurisdiction-ambiguous claims FAIL.
- Citation specificity: cite the specific statute section / case name +
  citation, not a general topic page.
- Not legal advice: the report describes what the law says; it must not be
  framed as advice for a specific situation."""

    def worker_guidance(self) -> str:
        return """\
- Target PRIMARY sources: official statute/regulation databases, court
  opinions (e.g. CourtListener, official court sites), and government
  publications. Append queries with the jurisdiction and source type
  (e.g. "statute", "case", "site:gov", a court name).
- Record for each legal source: jurisdiction, instrument type (statute /
  regulation / case / guidance), date/version, and whether it is currently in
  force, in the source notes.
- Prefer the official text over any summary of it; use commentary only to
  locate the primary source, then read and cite the primary source itself.
- kind="web" for these unless a true paper/preprint."""
