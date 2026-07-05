"""Adversarial verifier (docs/COMPREHENSIVE_RESEARCH_SPEC.md §3) — the trust
differentiator vs one-pass deep-research services.

For one finding, an INDEPENDENT, amnesiac session tries to REFUTE its claim:
local refutation query-gen → engine search + read of sources the finding did
NOT use → an Opus verdict on whether the independent evidence contradicts the
claim. A claim that survives is `verified`; one that's contradicted is
`refuted` (the synthesizer demotes it); inconclusive stays `unverified`.

It reuses the pipeline's search/select/read helpers — the verifier is, in
effect, one adversarially-framed pipeline pass that returns a verdict instead
of a finding.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
from src.profiles import Profile
from src.runspace import Runspace
from src.sessions import common, reader
from src.sessions.base import SessionError, SessionResult, run_role_session_async
from src.sessions.pipeline import (
    _gather_results,
    _pipeline_cfg,
    rerank_scores,
    select_urls,
)
from src.settings import Settings
from src.state import FindingMeta

_QUERYGEN_ROLE = "reader_subagent"  # cheap local refutation query-gen
_VERIFIER_ROLE = "verifier"          # the verdict — judgment work, Opus

_QUERYGEN_SYSTEM = """\
You are the search arm of an adversarial fact-checker. Given a research CLAIM,
generate web-search queries designed to surface evidence that would CONTRADICT
or DISPROVE it — counter-studies, dissenting expert positions, failed
replications, methodological critiques, more recent data that revises it.
Do NOT generate queries that merely re-confirm the claim.
PRIORITIZE the riskiest claim types: for an ABSENCE/NEGATIVE claim ("X is absent",
"no data on X", "not in the table"), search HARD for the very thing it says is
missing — a single hit disproves it. For a claim hinging on a specific NUMBER
(dose, sample size, concentration, endpoint), target the PRIMARY study for that
exact value. Respond ONLY via the enforced JSON schema."""

_VERDICT_SYSTEM = """\
You are an adversarial VERIFIER. You are given (a) a CLAIM from a research
finding and (b) INDEPENDENT evidence gathered specifically to challenge it
(from sources the original finding did NOT use). Judge ONLY from the evidence
shown.

status:
- "refuted"  — the independent evidence directly contradicts the claim, shows
  it to be wrong/overstated, or supersedes it with better data. Be specific in
  the note about what contradicts it.
- "verified" — the independent evidence is consistent with the claim and you
  found no credible contradiction despite looking for one.
- "uncertain" — the evidence is mixed, off-topic, or too thin to judge either
  way. Do NOT guess.

Hold a high bar for "refuted": a minor caveat or a single weak dissent is not a
refutation. note: one or two sentences justifying the verdict, citing what in
the evidence drove it.
SPECIAL CASE — absence/negative claims: a claim that "X is absent / no data
exists / not reported" is REFUTED the instant the evidence shows even ONE credible
instance of X. Absence is disproven by a single counterexample, so the bar to
refute these is LOW, not high — this is the failure mode that lets false negatives
into reports. For NUMERIC claims, a PRIMARY source contradicting the stated value
refutes it; a mere secondary restatement differing does not.
Respond ONLY via the enforced JSON schema."""


class RefutationQueries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["verified", "refuted", "uncertain"]
    note: str


# uncertain => leave the finding unverified (couldn't confirm either way).
_STATUS_MAP = {"verified": "verified", "refuted": "refuted", "uncertain": "unverified"}


def verify_finding(
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    profile: Profile,
    slug: str,
    meta: FindingMeta,
    body: str,
) -> tuple[str, str]:
    """Return (verification_status, verification_note) for one finding."""
    return asyncio.run(
        _verify_async(run, settings, ledger, cycle, profile, slug, meta, body)
    )


async def _verify_async(
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    profile: Profile,
    slug: str,
    meta: FindingMeta,
    body: str,
) -> tuple[str, str]:
    cfg = _pipeline_cfg(settings, profile)
    # Verification reads less than a full investigation — a handful of
    # independent challenges is enough to surface a contradiction.
    cfg = {**cfg, "max_reads": min(cfg["max_reads"], 6)}
    question = "challenge this claim: " + body[:200]

    # 1. refutation query-gen (local)
    try:
        qspawn = await run_role_session_async(
            run=run, settings=settings, ledger=ledger, cycle=cycle,
            session_type="reader", role=_QUERYGEN_ROLE,
            system_prompt=_QUERYGEN_SYSTEM,
            user_prompt=f"CLAIM:\n{body}\n\nGenerate up to {cfg['queries_per_question']} refutation queries.",
            tools=[], output_model=RefutationQueries,
        )
        queries = [q.strip() for q in qspawn.structured.queries if q.strip()][
            : cfg["queries_per_question"]
        ]
    except SessionError as exc:
        run.log(f"verifier {slug}: query-gen failed ({exc}); cannot verify")
        return "unverified", f"verification skipped: query-gen failed ({exc})"
    if not queries:
        return "unverified", "verification skipped: no refutation queries generated"

    # 2. search + select INDEPENDENT sources (exclude the finding's own URLs)
    providers = profile.pipeline_search_providers(settings)
    results = await _gather_results(providers, queries, run)
    sources = run.load_sources()
    own_urls = {
        common.normalize_url(sources.root[sid].url)
        for sid in meta.source_ids
        if sid in sources.root
    }
    rerank_fn = rerank_scores if settings.worker_pipeline.rerank else None
    selected = select_urls(results, own_urls, cfg, profile.url_preferences(),
                           question=question, rerank_fn=rerank_fn)

    # 3. read the challengers
    reads: list[tuple[str, reader.ReaderOutput]] = []

    async def read_one(item: dict[str, Any]) -> None:
        try:
            out, _ = await reader.read_source(
                run=run, settings=settings, ledger=ledger, cycle=cycle,
                url=item["url"], question=question, why=item.get("snippet", "")[:200],
                # Refutation independence: never consume (or overwrite) the
                # breadth-phase completed cache — a breadth-framed digest can
                # omit exactly the counter-evidence a challenge read exists to
                # find, biasing the verdict toward a false "verified".
                bypass_completed=True,
            )
        except SessionError:
            return
        if out.useful:
            reads.append((item["url"], out))

    await asyncio.gather(*(read_one(it) for it in selected))

    if not reads:
        # No independent challenge could be read — honest non-result, not a pass.
        return "unverified", (
            f"verification inconclusive: no independent challenging sources "
            f"could be read ({len(selected)} tried)"
        )

    # 4. verdict (Opus)
    evidence = "\n\n".join(
        f"## {out.title} (credibility {out.credibility})\n{out.summary_markdown}"
        for _url, out in reads
    )
    try:
        vspawn = await run_role_session_async(
            run=run, settings=settings, ledger=ledger, cycle=cycle,
            session_type="evaluator", role=_VERIFIER_ROLE,
            system_prompt=_VERDICT_SYSTEM,
            user_prompt=f"CLAIM:\n{body}\n\nINDEPENDENT EVIDENCE (gathered to challenge it):\n\n{evidence}",
            tools=[], output_model=Verdict,
        )
        verdict: Verdict = vspawn.structured
    except SessionError as exc:
        return "unverified", f"verification inconclusive: verdict failed ({exc})"

    status = _STATUS_MAP[verdict.status]
    note = f"[{len(reads)} independent sources checked] {verdict.note}".strip()
    return status, note
