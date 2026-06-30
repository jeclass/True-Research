"""Synthesizer session (Opus): findings -> REPORT.md with a deterministic
citation pass (CLAUDE.md §6, invariant 3). The model composes; the engine
verifies every [src-...] citation resolves against sources.json, refuses
unknowns, and appends the limitations/decisions section and source appendix
itself so they cannot be fabricated or omitted."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
from src.runspace import REPORT_FILE, REPORT_PDF_FILE, Runspace
from src.sessions import common
from src.sessions.base import SessionResult, SynthesisError, run_role_session
from src.settings import Settings

_ROLE = "synthesizer"
_TOOLS = ["Read", "Glob", "Grep"]

_SYSTEM_PROMPT = """\
You are the SYNTHESIZER. Compose the final research report from the findings
provided — and ONLY from them. No new research; no claims that do not appear
in a finding.

Report rules:
- report_markdown: a complete markdown report. Lead with the answer: a direct
  summary of what the evidence supports. Then evidence sections organized by
  theme, then a section on contradictions and open uncertainties.
- Be COMPREHENSIVE, not minimal. Where the findings provide directly-relevant
  background or comparative context — how the recommendation compares to the
  standard alternatives, the key mechanism behind it, important caveats and
  limitations a reader needs to act safely — INCLUDE it. A complete answer
  contextualizes its recommendation; do not omit relevant context the findings
  contain merely because it does not change WHICH option is recommended.
- EVERY factual claim ends with its [src-id] citation(s), copied faithfully
  from the findings. A claim you cannot cite does not go in the report.
- ABSENCE IS HARD TO PROVE. A negative claim — "X is absent / not reported / no
  data exists / not studied / not in the table" — is only valid when a finding
  AFFIRMATIVELY establishes it from a fully-read source. If the findings simply do
  not mention X, write "not found among the sources reviewed," never "X does not
  exist." A source that was truncated or that omits a table is not evidence the
  data doesn't exist (this is the single most common error mode — a missing
  comparator row or dosing line becomes a false "absent").
- PRIMARY SOURCES WIN ON SPECIFIC NUMBERS. For doses, sample sizes, concentrations,
  effect sizes, and endpoints, prefer the value from the PRIMARY study (the RCT or
  meta-analysis itself) over a blog/aggregator/review. If findings disagree on a
  number, surface the discrepancy and favor the primary — do not silently adopt a
  secondary's figure.
- If the run ended early (you will be told), say plainly what was and was not
  covered. Do not pad.
- Some findings carry a VERIFICATION tag (an independent adversarial check).
  Present VERIFIED findings normally. For a REFUTED finding, do NOT lead with
  its claim — present it as contested, state plainly that an independent check
  contradicted it, and weight the conclusion away from it. Unverified findings
  are presented normally (absence of a check is not a mark against them).
- Do NOT write a 'Limitations & decisions' section or a source list — the
  engine appends both from its own records.

Respond ONLY via the enforced JSON schema."""


class SynthesizerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_markdown: str


def _build_user_prompt(run: Runspace) -> str:
    questions = run.load_questions()
    sources = run.load_sources()
    reason = run.meta.finish_reason or "unknown"
    status_note = (
        "The run ended CONCLUSIVELY — the evaluator passed the findings."
        if reason == "conclusive"
        else f"The run ended EARLY (reason: {reason}) — this is a PARTIAL report; "
        "scope your claims to what the findings actually cover."
    )
    # Only factual-track findings are admissible material for the synthesis;
    # community findings (if any) are appended by the engine into a separate
    # quarantined section the model never sees (docs/COMMUNITY_LENS_SPEC.md).
    return (
        f"# Research question\n{run.meta.question}\n\n"
        f"# Run status\n{status_note}\n\n"
        f"# Question ledger\n{common.questions_digest(questions)}\n\n"
        f"# Source registry\n{common.sources_digest(sources)}\n\n"
        f"# Findings (full text — your only admissible material)\n"
        f"{common.findings_digest(run, full_bodies=True, only_tracks={'factual'})}\n"
    )


def _community_section(run: Runspace, settings: Settings, community: dict) -> str:
    """Engine-built, model-never-saw-it section for community-track findings.
    Returns '' when there are none (default runs) — so the report is unchanged."""
    if not community:
        return ""
    from src.lenses import lens_for_track

    lens = lens_for_track("community", settings.lenses)
    title = lens.report_section_title() if lens else "Community & practitioner perspective"
    framing = lens.report_section_framing() if lens else ""
    blocks = [f"\n\n## {title}\n\n{framing}\n"]
    for _slug, (meta, body) in sorted(community.items()):
        blocks.append(f"\n{body.strip()}\n")
    return "".join(blocks)


def _verification_section(factual: dict) -> str:
    """Engine-built summary of the adversarial verification wave (§3). Lists
    REFUTED findings explicitly so a contradicted claim is surfaced even if the
    model under-weights it. Returns '' when nothing was verified (default runs
    unchanged)."""
    checked = [
        (slug, m, b)
        for slug, (m, b) in factual.items()
        if m.verification_status in ("verified", "refuted")
    ]
    if not checked:
        return ""
    verified = [c for c in checked if c[1].verification_status == "verified"]
    refuted = [c for c in checked if c[1].verification_status == "refuted"]
    out = [
        "\n\n## Verification",
        "",
        f"_An independent adversarial check tried to refute the load-bearing "
        f"findings: {len(verified)} survived (verified), {len(refuted)} were "
        f"contradicted (refuted). Refuted claims are demoted above and listed "
        f"here._",
        "",
    ]
    if refuted:
        out.append("**Refuted / contested claims:**")
        for slug, meta, _body in sorted(refuted):
            out.append(f"- `{slug}` (question {meta.question_id}): {meta.verification_note}")
    else:
        out.append("No load-bearing finding was refuted by independent verification.")
    return "\n".join(out) + "\n"


def _synthesize_factual(
    run: Runspace, settings: Settings, ledger: Ledger, cycle: int, sources
) -> tuple[str, SessionResult]:
    """Spawn the synthesizer; on a citation-pass failure (the model citing source
    ids absent from sources.json — observed 2026-06-24: DeepSeek Pro hallucinated
    `src-<qid>-finding` ids) retry with explicit feedback listing the valid ids,
    then DEGRADE by replacing any still-unresolvable citation with an explicit
    [citation-unresolved] marker. The final step must never crash a completed run,
    and invariant 3 still holds — no fabricated source id survives into the report."""
    attempts = max(1, min(settings.retry.attempts, 3))
    valid_ids = sorted(sources.root)
    feedback = ""
    spawn = None
    body = ""
    for attempt in range(1, attempts + 1):
        spawn = run_role_session(
            run=run,
            settings=settings,
            ledger=ledger,
            cycle=cycle,
            session_type="synthesizer",
            role=_ROLE,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(run) + feedback,
            tools=_TOOLS,
            output_model=SynthesizerOutput,
        )
        body = spawn.structured.report_markdown.strip()
        unknown = sorted({c for c in common.CITATION_RE.findall(body) if c not in sources.root})
        if not unknown:
            return body, spawn
        run.log_decision(
            f"synthesizer attempt {attempt}/{attempts}: cited non-existent source ids "
            f"{unknown}; " + ("retrying with feedback" if attempt < attempts else "neutralizing")
        )
        shown = ", ".join(valid_ids[:60]) or "(none)"
        feedback = (
            f"\n\nCORRECTION: your previous draft cited source ids that DO NOT exist "
            f"in sources.json: {unknown}. Every [src-...] citation MUST be exactly one "
            f"of these ids: {shown}. Re-emit the full report using only valid ids, and "
            f"drop any claim you cannot cite to a valid id."
        )
    # Retries exhausted — neutralize the unresolvable citations so the report still
    # emits (a finished run must yield a report), with the gap made explicit rather
    # than silently dropped or fabricated.
    unknown = sorted({c for c in common.CITATION_RE.findall(body) if c not in sources.root})
    for u in unknown:
        body = body.replace(f"[{u}]", "[citation-unresolved]")
    run.log_decision(
        f"synthesizer: {len(unknown)} citation(s) still unresolvable after {attempts} "
        f"attempts ({unknown}); replaced with [citation-unresolved] so the report emits "
        "instead of crashing the final step (invariant 3: no fabricated source survives)"
    )
    return body, spawn


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    all_findings = run.load_findings()
    sources = run.load_sources()
    factual = {s: p for s, p in all_findings.items() if p[0].track == "factual"}
    community = {s: p for s, p in all_findings.items() if p[0].track == "community"}

    if factual:
        factual_body, metrics = _synthesize_factual(run, settings, ledger, cycle, sources)
    else:
        # No factual findings — honest empty body, no model call. A
        # community-only run still gets its quarantined section below.
        factual_body = (
            f"# Report: {run.meta.question}\n\n"
            "No factual findings were produced before the run ended. There is "
            "nothing to report in the evidence sections."
        )
        metrics = None

    # Community section is engine-appended (quarantined); the model never saw
    # these findings, so it cannot fold anecdote into the factual synthesis.
    community_md = _community_section(run, settings, community)
    verification_md = _verification_section(factual)
    report_body = factual_body + verification_md + community_md

    # --- deterministic citation pass (invariant 3) ---------------------------
    cited = common.CITATION_RE.findall(report_body)
    unknown = sorted({c for c in cited if c not in sources.root})
    if unknown:
        raise SynthesisError(
            f"report cites source ids missing from sources.json: {unknown}; "
            "refusing to emit (invariant 3)"
        )
    if factual and not common.CITATION_RE.findall(factual_body):
        raise SynthesisError(
            "report contains no [src-...] citations despite findings existing; "
            "refusing to emit (invariant 3)"
        )
    findings = all_findings  # downstream logging counts all tracks

    reason = run.meta.finish_reason or "unknown"
    banner = (
        ""
        if reason == "conclusive"
        else f"\n> **PARTIAL REPORT** — run ended early (reason: {reason}).\n"
    )

    decisions = run.decisions()
    limitations = ["", "## Limitations & decisions", ""]
    limitations += [f"- {d}" for d in decisions] or ["- no decisions were logged"]

    appendix = ["", "## Source registry", ""]
    used = sorted(set(cited))
    if used:
        for sid in used:
            rec = sources.root[sid]
            appendix.append(
                f"- `{sid}` — {rec.title} ({rec.kind}, credibility {rec.credibility}): "
                f"{rec.url}"
            )
            # Span-level citation anchors (roadmap): the exact wording behind this
            # source's contribution, so a reader can verify a claim without
            # re-fetching the source. Capped at 3 — an enrichment, not a transcript.
            appendix += [f'  > "{q.strip()}"' for q in rec.excerpts[:3]]
    else:
        appendix += ["- no sources cited"]

    report_md = banner + report_body + "\n" + "\n".join(limitations + appendix) + "\n"
    run.write_text(REPORT_FILE, report_md)
    run.log(
        f"synthesizer: wrote REPORT.md ({len(findings)} findings, "
        f"{len(used)} cited sources, reason={reason})"
    )

    # Convenience artifact: REPORT.pdf next to REPORT.md. Pure-Python render, so a
    # missing dep / render error is a logged DECISION (invariant 8), never a crash —
    # the markdown is the source of truth and already on disk.
    if settings.emit_pdf:
        from src.tools.report_pdf import render_markdown_pdf

        ok, detail = render_markdown_pdf(report_md, run.root / REPORT_PDF_FILE)
        run.log(f"synthesizer: PDF {'written' if ok else 'skipped'} — {detail}")
        if not ok:
            run.log_decision(f"REPORT.pdf not generated ({detail}); REPORT.md is complete.")

    role_cfg = settings.roles[_ROLE]
    return SessionResult(
        session_type="synthesizer",
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        input_tokens=metrics.input_tokens if metrics else 0,
        output_tokens=metrics.output_tokens if metrics else 0,
        cached_tokens=metrics.cached_tokens if metrics else 0,
        usd=metrics.usd if metrics else 0.0,
        wall_seconds=metrics.wall_seconds if metrics else 0.0,
        summary=f"report: {len(findings)} findings, {len(used)} sources cited",
    )
