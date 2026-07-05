"""Deterministic guards of the real (sdk-backend) session modules — all
testable with zero LLM calls."""

from pathlib import Path

import pytest
import yaml

from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import common, synthesizer, worker
from src.sessions.base import SynthesisError, WorkerError
from src.settings import Settings
from src.state import (
    FindingMeta,
    OpenQuestion,
    QuestionList,
    SourceRecord,
    SourceRegistry,
    utcnow,
)
from tests.conftest import BASE_CONFIG


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["session"]["backend"] = "sdk"
    return Settings.model_validate(raw)


@pytest.fixture
def run(tmp_path: Path):
    r = Runspace.create(tmp_path / "runs", "test question", "general")
    yield r
    r.release_lock()


def _register_source(run: Runspace, source_id: str) -> None:
    registry = run.load_sources()
    registry.root[source_id] = SourceRecord(
        url=f"https://example.org/{source_id}",
        title=source_id,
        kind="web",
        credibility=80,
        retrieved_at=utcnow(),
    )
    run.save_sources(registry)


def test_merge_sources_rejects_id_collision_with_different_url(run):
    _register_source(run, "src-a")
    with pytest.raises(WorkerError, match="collision"):
        common.merge_sources(
            run,
            [{"id": "src-a", "url": "https://other.org", "title": "t",
              "kind": "web", "credibility": 50, "notes": ""}],
            WorkerError,
        )


def test_merge_sources_url_normalized_variant_is_noop_not_collision(run):
    # Final review: the collision check compared RAW urls, so two parallel
    # questions reading normalized-equal variants ('…/page' vs '…/page/')
    # raised a spurious "source id collision" WorkerError that discarded the
    # losing question's whole cycle. Normalized-equal = same source = no-op.
    registry = run.load_sources()
    registry.root["src-a"] = SourceRecord(
        url="https://x.org/page", title="src-a", kind="web", credibility=80,
        retrieved_at=utcnow(),
    )
    run.save_sources(registry)

    merged = common.merge_sources(
        run,
        [{"id": "src-a", "url": "https://x.org/page/", "title": "t",
          "kind": "web", "credibility": 50, "notes": ""}],
        WorkerError,
    )
    assert merged.root["src-a"].url == "https://x.org/page"  # original kept

    # a GENUINELY different url still collides
    with pytest.raises(WorkerError, match="collision"):
        common.merge_sources(
            run,
            [{"id": "src-a", "url": "https://x.org/other-page", "title": "t",
              "kind": "web", "credibility": 50, "notes": ""}],
            WorkerError,
        )


def test_merge_sources_rejects_bad_id_and_credibility(run):
    with pytest.raises(WorkerError, match="does not match"):
        common.merge_sources(
            run,
            [{"id": "SRC_BAD!", "url": "https://x.org", "title": "t",
              "kind": "web", "credibility": 50, "notes": ""}],
            WorkerError,
        )
    with pytest.raises(WorkerError, match="credibility"):
        common.merge_sources(
            run,
            [{"id": "src-ok", "url": "https://x.org", "title": "t",
              "kind": "web", "credibility": 101, "notes": ""}],
            WorkerError,
        )


def test_merge_sources_persists_excerpts(run):
    # roadmap (span-level citation anchors): excerpts proposed alongside a new
    # source must land on the persisted SourceRecord; absent entirely defaults
    # to [] (backward compatible with callers/registries predating the field).
    registry = common.merge_sources(
        run,
        [{"id": "src-quoted", "url": "https://x.org/a", "title": "t", "kind": "web",
          "credibility": 80, "notes": "", "excerpts": ["The exact wording cited."]}],
        WorkerError,
    )
    assert registry.root["src-quoted"].excerpts == ["The exact wording cited."]

    registry = common.merge_sources(
        run,
        [{"id": "src-bare", "url": "https://x.org/b", "title": "t", "kind": "web",
          "credibility": 80, "notes": ""}],   # no "excerpts" key at all
        WorkerError,
    )
    assert registry.root["src-bare"].excerpts == []


def test_next_question_id_continues_numbering():
    questions = QuestionList(
        [
            OpenQuestion(id="q-001", question="a", priority=3, created_by="initializer"),
            OpenQuestion(id="q-007", question="b", priority=3, created_by="evaluator"),
        ]
    )
    assert common.next_question_id(questions) == "q-008"


def test_worker_apply_resolved_rejects_citationless_finding(run, settings):
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="A claim with no citation.", confidence=0.9),
        sources=[],
        progress_note="n",
    )
    with pytest.raises(WorkerError, match="no \\[src-"):
        worker._apply_resolved(run, settings, target, output, cycle=1, read_urls=set())


def test_worker_apply_resolved_rejects_unregistered_citation(run, settings):
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Claim. [src-ghost]", confidence=0.9),
        sources=[],
        progress_note="n",
    )
    with pytest.raises(WorkerError, match="src-ghost"):
        worker._apply_resolved(run, settings, target, output, cycle=1, read_urls=set())


def test_read_gate_rejects_unread_source(run, settings):
    """A source whose URL was never read this run cannot be cited when
    require_reads is on (the ultimate-depth invariant)."""
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Claim. [src-a]", confidence=0.8),
        sources=[
            worker.ProposedSource(id="src-a", url="https://example.org/a", title="A",
                                  kind="web", credibility=85)
        ],
        progress_note="n",
    )
    with pytest.raises(WorkerError, match="never read via read_source"):
        worker._apply_resolved(
            run, settings, target, output, cycle=1, read_urls=set()
        )


def test_read_gate_allows_prior_cycle_registry_source(run, settings):
    """A source already in sources.json (read in a prior cycle) may be reused
    without re-reading."""
    _register_source(run, "src-old")  # registers https://example.org/src-old
    target = OpenQuestion(id="q-002", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Reuse. [src-old]", confidence=0.7),
        sources=[
            worker.ProposedSource(id="src-old", url="https://example.org/src-old",
                                  title="src-old", kind="web", credibility=80)
        ],
        progress_note="n",
    )
    summary = worker._apply_resolved(
        run, settings, target, output, cycle=2, read_urls=set()
    )
    assert "q-002-c02" in summary


def test_read_gate_disabled_admits_unread_source(run, tmp_path):
    """require_reads=false (no-egress mode) admits snippet-only sources."""
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["session"]["backend"] = "sdk"
    raw["reader"]["require_reads"] = False
    lax = Settings.model_validate(raw)
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Snippet claim. [src-a]", confidence=0.5),
        sources=[
            worker.ProposedSource(id="src-a", url="https://example.org/a", title="A",
                                  kind="web", credibility=60)
        ],
        progress_note="n",
    )
    summary = worker._apply_resolved(
        run, lax, target, output, cycle=1, read_urls=set()
    )
    assert "q-001-c01" in summary
    assert any("require_reads=false" in d for d in run.decisions())


def test_worker_apply_resolved_happy_path_writes_state(run, settings):
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Claim. [src-a]", confidence=0.8),
        sources=[
            worker.ProposedSource(
                id="src-a", url="https://example.org/a", title="A", kind="web",
                credibility=85,
            )
        ],
        progress_note="n",
    )
    # The URL was read this session, so the read-gate admits it.
    summary = worker._apply_resolved(
        run, settings, target, output, cycle=2,
        read_urls={"https://example.org/a"},
    )
    assert "q-001-c02" in summary
    questions = run.load_questions()
    assert questions.get("q-001").status == "resolved"
    assert questions.get("q-001").resolved_by_finding == "q-001-c02"
    meta, body = run.load_findings()["q-001-c02"]
    assert meta.source_ids == ["src-a"] and "[src-a]" in body
    assert "src-a" in run.load_sources().root


def test_worker_apply_resolved_propagates_proposed_source_excerpts(run, settings):
    # roadmap (span-level citation anchors), agentic-mode path: ProposedSource.
    # excerpts (the worker's copy-forward of read_source's KEY QUOTES block) must
    # flow through _apply_resolved -> merge_sources onto the persisted SourceRecord.
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Claim. [src-a]", confidence=0.8),
        sources=[
            worker.ProposedSource(
                id="src-a", url="https://example.org/a", title="A", kind="web",
                credibility=85, excerpts=["copied verbatim from read_source"],
            )
        ],
        progress_note="n",
    )
    worker._apply_resolved(
        run, settings, target, output, cycle=2, read_urls={"https://example.org/a"},
    )
    assert run.load_sources().root["src-a"].excerpts == ["copied verbatim from read_source"]


def test_format_read_result_includes_key_quotes_block_only_when_present():
    # the read_source MCP tool's returned text must surface KEY QUOTES so the
    # agentic worker has verbatim text available to copy into ProposedSource.
    # useful=True + key_quotes triggers the block; no quotes -> no block at all.
    from src.sessions.reader import ReaderOutput
    from src.sessions.worker import _format_read_result

    with_quotes = ReaderOutput(
        useful=True, title="t", kind="web", credibility=80, notes="n",
        summary_markdown="s", key_quotes=["exact wording"],
    )
    without_quotes = ReaderOutput(
        useful=True, title="t", kind="web", credibility=80, notes="n",
        summary_markdown="s",
    )
    with_text = _format_read_result(with_quotes, "https://x")
    without_text = _format_read_result(without_quotes, "https://x")
    assert "KEY QUOTES" in with_text and '"exact wording"' in with_text
    assert "KEY QUOTES" not in without_text

    # Final review: the summary + quotes are derived from attacker-controlled
    # page text — they must sit INSIDE the untrusted fence. The engine/reader-
    # adjudicated metadata header (TITLE/KIND/CREDIBILITY/URL) stays outside.
    for text in (with_text, without_text):
        open_i = text.index("<<<UNTRUSTED_WEB_CONTENT>>>")
        close_i = text.rindex("<<<END_UNTRUSTED_WEB_CONTENT>>>")
        assert text.index("TITLE:") < open_i
        assert text.index("URL: https://x") < open_i
        assert open_i < text.index("SUMMARY:") < close_i
    open_i = with_text.index("<<<UNTRUSTED_WEB_CONTENT>>>")
    close_i = with_text.rindex("<<<END_UNTRUSTED_WEB_CONTENT>>>")
    assert open_i < with_text.index("KEY QUOTES") < close_i
    assert open_i < with_text.index('"exact wording"') < close_i
    assert "reader digest" in with_text          # fence label names the surface


def test_synthesizer_without_findings_needs_no_model(run, settings, tmp_path):
    """No findings -> honest empty report, zero LLM calls, partial banner."""
    run.mark_finishing("budget")
    result = synthesizer.run(run, settings, 0, Ledger(run))
    report = (run.root / "REPORT.md").read_text()
    assert "PARTIAL REPORT" in report and "budget" in report
    assert "nothing to report" in report.lower()
    assert result.usd == 0.0


def test_synthesizer_report_shows_excerpts_as_inline_citations(run, settings, tmp_path, monkeypatch):
    # roadmap (span-level citation anchors): a cited source with excerpts must
    # render them as blockquotes under its appendix entry — the "true inline
    # citation" benefit, so a reader can verify a claim without re-fetching the
    # source. A source with no excerpts (e.g. an older registry / agentic-mode
    # source that proposed none) must render exactly as before (no blockquote).
    registry = run.load_sources()
    registry.root["src-quoted"] = SourceRecord(
        url="https://x.org/a", title="Quoted Source", kind="web", credibility=80,
        retrieved_at=utcnow(), excerpts=["The exact supporting sentence."],
    )
    registry.root["src-bare"] = SourceRecord(
        url="https://x.org/b", title="Bare Source", kind="web", credibility=80,
        retrieved_at=utcnow(),
    )
    run.save_sources(registry)
    run.write_finding(
        "q-001-c01",
        FindingMeta(question_id="q-001", source_ids=["src-quoted", "src-bare"], confidence=0.8),
        "A claim [src-quoted] and another [src-bare].",
    )
    run.mark_finishing("conclusive")

    class _Spawn:
        structured = type("O", (), {
            "report_markdown": "# Report\n\nA claim [src-quoted] and another [src-bare]."
        })()
        input_tokens = output_tokens = cached_tokens = 1
        usd = 0.0
        wall_seconds = 0.1
        num_turns = 1

    monkeypatch.setattr(synthesizer, "run_role_session", lambda **kw: _Spawn())
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    assert '> "The exact supporting sentence."' in report
    # the quote appears directly under its OWN source's bullet (sorted("src-bare",
    # "src-quoted") alphabetically -> bare first, then quoted, then its excerpt)
    bare_idx = report.index("`src-bare`")
    quoted_idx = report.index("`src-quoted`")
    excerpt_idx = report.index('> "The exact supporting sentence."')
    assert bare_idx < quoted_idx < excerpt_idx
    # the bare source's own line carries NO blockquote (no excerpts registered)
    between = report[bare_idx:quoted_idx]
    assert ">" not in between


def test_synthesizer_excerpt_rendering_neutralizes_newlines_and_image_markdown(
    run, settings, tmp_path, monkeypatch
):
    # Final review, defense in depth at the RENDER site (registries written
    # before the reader normalized quotes may still hold raw excerpts): an
    # excerpt with an embedded newline could escape the blockquote and inject
    # markdown — "![](...)" being a zero-click image-exfil channel. The render
    # must collapse whitespace to one line, then escape "![".
    registry = run.load_sources()
    registry.root["src-evil"] = SourceRecord(
        url="https://x.org/e", title="Evil", kind="web", credibility=10,
        retrieved_at=utcnow(),
        excerpts=["line one\n- bullet ![](https://evil.example/x)"],
    )
    run.save_sources(registry)
    run.write_finding(
        "q-001-c01",
        FindingMeta(question_id="q-001", source_ids=["src-evil"], confidence=0.8),
        "A claim [src-evil].",
    )
    run.mark_finishing("conclusive")

    class _Spawn:
        structured = type("O", (), {
            "report_markdown": "# Report\n\nA claim [src-evil]."
        })()
        input_tokens = output_tokens = cached_tokens = 1
        usd = 0.0
        wall_seconds = 0.1
        num_turns = 1

    monkeypatch.setattr(synthesizer, "run_role_session", lambda **kw: _Spawn())
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    quote_lines = [ln for ln in report.splitlines() if ln.lstrip().startswith(">") and "line one" in ln]
    assert len(quote_lines) == 1                      # ONE blockquote line — newline collapsed
    line = quote_lines[0]
    assert "!\\[" in line                             # image-exfil channel escaped
    assert "![](https://evil.example/x)" not in report  # raw image markdown gone
    assert "- bullet" in line                         # payload stayed INSIDE the quote line


# --- synthesizer output-contract self-heal (observed run 20260702-150058-119b:
# --cheap synthesizer on DeepSeek V4 Pro crashed the run twice at the finish
# line — once on schema drift (extra_forbidden), once on a zero-citation
# report). Contract: reroll same endpoint up to 2 more times with the failure
# reason appended, then ONE final attempt on the role's fallback endpoint,
# every extra attempt a logged DECISION; if everything fails, the loud typed
# crash stays and invariant 3 never weakens. ------------------------------------


def _mk_spawn(body: str):
    class _Spawn:
        structured = type("O", (), {"report_markdown": body})()
        input_tokens = output_tokens = cached_tokens = 1
        usd = 0.0
        wall_seconds = 0.1
        num_turns = 1

    return _Spawn()


def _seed_cited_finding(run: Runspace) -> None:
    _register_source(run, "src-a")
    run.write_finding(
        "q-001-c01",
        FindingMeta(question_id="q-001", source_ids=["src-a"], confidence=0.8),
        "A claim [src-a].",
    )
    run.mark_finishing("conclusive")


@pytest.fixture
def fb_settings(tmp_path: Path) -> Settings:
    """SDK-backend settings whose synthesizer endpoint has a configured fallback
    (mirrors config.yaml's deepseek -> anthropic reliability net)."""
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["session"]["backend"] = "sdk"
    raw["endpoints"]["anthropic"]["fallback"] = {"endpoint": "local", "model": "fb-model"}
    return Settings.model_validate(raw)


def test_synthesizer_schema_drift_rerolls_same_endpoint_with_reason(
    run, settings, monkeypatch
):
    """Failure mode (a), run 20260702-150058-119b: structured output rejected
    with pydantic extra_forbidden. One reroll on the SAME endpoint, the concrete
    rejection appended to the retry prompt, success emits a normal report, and
    the reroll is a logged DECISION (invariant 8)."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise SynthesisError(
                "synthesizer structured output failed validation:\n"
                "1 validation error for SynthesizerOutput\nreport\n"
                "  Extra inputs are not permitted [type=extra_forbidden]"
            )
        return _mk_spawn("# Report\n\nA claim [src-a].")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    assert len(calls) == 2
    # same endpoint: the reroll did NOT touch the role's routing
    assert calls[1]["settings"].roles["synthesizer"].endpoint == "anthropic"
    # concrete failure reason appended to the retry's user prompt
    assert "rejected" in calls[1]["user_prompt"]
    assert "extra_forbidden" in calls[1]["user_prompt"]
    assert "[src-" in calls[1]["user_prompt"]
    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    assert "A claim [src-a]." in report
    assert any("reroll" in d for d in run.decisions())


def test_synthesizer_citation_drop_rerolls_same_endpoint_with_reason(
    run, settings, monkeypatch
):
    """Failure mode (b), same run: the report parsed fine but carried ZERO
    [src-...] citations. Same reroll contract; invariant 3 is enforced by
    rerolling, never by accepting the uncited report."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return _mk_spawn("# Report\n\nA confident but entirely uncited claim.")
        return _mk_spawn("# Report\n\nA claim [src-a].")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    assert len(calls) == 2
    assert "rejected" in calls[1]["user_prompt"]
    assert "citation" in calls[1]["user_prompt"].lower()
    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    assert "A claim [src-a]." in report
    assert "entirely uncited" not in report  # the uncited draft never emitted
    assert any("reroll" in d for d in run.decisions())


def test_synthesizer_rerolls_exhausted_escalates_once_to_fallback_endpoint(
    run, fb_settings, monkeypatch
):
    """Rerolls exhausted (initial + 2) -> exactly ONE final attempt on the
    role's configured fallback endpoint (API-enforced output_format there
    structurally eliminates schema drift), logged as a DECISION."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        if len(calls) <= 3:
            raise SynthesisError("synthesizer structured output failed validation: drift")
        return _mk_spawn("# Report\n\nA claim [src-a].")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    synthesizer.run(run, fb_settings, cycle=1, ledger=Ledger(run))

    assert len(calls) == 4
    for kw in calls[:3]:  # initial + 2 rerolls stay on the primary endpoint
        assert kw["settings"].roles["synthesizer"].endpoint == "anthropic"
    fb_role = calls[3]["settings"].roles["synthesizer"]
    assert fb_role.endpoint == "local" and fb_role.model == "fb-model"
    # the correction block is rebuilt from the base prompt each attempt — it
    # must appear exactly ONCE in the 4th attempt's prompt, never accumulate
    assert calls[3]["user_prompt"].count("CORRECTION:") == 1
    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    assert "A claim [src-a]." in report
    assert any("fallback" in d for d in run.decisions())


def test_synthesizer_all_output_attempts_fail_stays_a_loud_typed_error(
    run, fb_settings, monkeypatch
):
    """Everything fails (3 primary + 1 fallback) -> the loud SynthesisError
    crash-with-state-preserved behavior remains (§0: no silent failures);
    no REPORT.md is emitted."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        return _mk_spawn("# Report\n\nStill no citations at all.")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    with pytest.raises(SynthesisError, match="invariant 3"):
        synthesizer.run(run, fb_settings, cycle=1, ledger=Ledger(run))

    assert len(calls) == 4
    assert not (run.root / "REPORT.md").exists()


def test_synthesizer_transport_class_error_propagates_without_rerolls(
    run, fb_settings, monkeypatch
):
    """A TRANSPORT-class SynthesisError (fallback_eligible) already went through
    the session layer's own endpoint fallback — the synthesizer must NOT stack
    output-class rerolls on top of it."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        exc = SynthesisError("synthesizer session failed after 3 attempts (transient)")
        exc.fallback_eligible = True
        raise exc

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    with pytest.raises(SynthesisError, match="transient"):
        synthesizer.run(run, fb_settings, cycle=1, ledger=Ledger(run))
    assert len(calls) == 1


def test_synthesizer_rerolls_exhausted_no_fallback_raises_after_three(
    run, settings, monkeypatch
):
    """No fallback endpoint configured: the ladder is exactly initial + 2
    rerolls (3 spawn calls), then the loud typed SynthesisError stands —
    no fourth attempt, no REPORT.md."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        raise SynthesisError("synthesizer structured output failed validation: drift")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    with pytest.raises(SynthesisError, match="drift"):
        synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    assert len(calls) == 3
    assert not (run.root / "REPORT.md").exists()


# --- all-hallucinated-citation drafts (review 2026-07-02, Important #1): a
# draft whose citations are ALL invalid survives the _spawn_report ladder
# (it HAS citations), exhausts the feedback loop, then neutralization strips
# every [src-x] -> the body would reach run()'s invariant-3 zero-citation
# check and crash a finished run. Contract: one extra full ladder pass with an
# all-ids-invalid correction, then the honest "nothing citable" report —
# never a crash, and no uncited claim ever ships as fact. ---------------------


def test_synthesizer_all_hallucinated_citations_emit_honest_report(
    run, settings, monkeypatch
):
    """Every attempt (feedback loop AND the extra ladder pass) cites only
    invalid ids -> the honest nothing-citable report emits instead of a
    SynthesisError crash; both the extra pass and the fallback emission are
    logged DECISIONS (invariant 8)."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        return _mk_spawn("# Report\n\nA confident claim [src-ghost].")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))  # must NOT raise

    # 3 feedback-loop attempts + 1 extra ladder pass
    assert len(calls) == 4
    # the extra pass prompt explains ALL ids were invalid and lists valid ones
    assert "CORRECTION" in calls[3]["user_prompt"]
    assert "src-ghost" in calls[3]["user_prompt"]
    assert "src-a" in calls[3]["user_prompt"]
    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    # honest posture: no hallucinated id, no neutralized-citation residue
    # presented as fact, an explicit could-not-attribute statement
    assert "[src-ghost]" not in report
    assert "could not be attributed" in report.lower()
    assert "confident claim" not in report  # the hallucinated draft never ships
    decisions = run.decisions()
    assert any("extra" in d and "ladder" in d for d in decisions)
    assert any("honest" in d.lower() for d in decisions)


def test_synthesizer_all_hallucinated_recovers_on_extra_ladder_pass(
    run, settings, monkeypatch
):
    """The extra ladder pass produces a validly-cited draft -> normal report,
    no honest fallback."""
    _seed_cited_finding(run)
    calls = []

    def fake(**kw):
        calls.append(kw)
        if len(calls) <= 3:
            return _mk_spawn("# Report\n\nA confident claim [src-ghost].")
        return _mk_spawn("# Report\n\nA claim [src-a].")

    monkeypatch.setattr(synthesizer, "run_role_session", fake)
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    assert len(calls) == 4
    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    assert "A claim [src-a]." in report
    assert "[src-ghost]" not in report
    assert "could not be attributed" not in report.lower()


def test_orphaned_in_progress_question_is_picked_first():
    questions = QuestionList(
        [
            OpenQuestion(id="q-001", question="orphan", priority=2,
                         created_by="initializer", status="in_progress"),
            OpenQuestion(id="q-002", question="fresh", priority=5,
                         created_by="initializer", status="open"),
        ]
    )
    target = common.pick_target_question(questions)
    assert target is not None and target.id == "q-001"  # orphan beats higher-priority open


def test_synthesizer_citation_regex_matches_engine_convention():
    text = "Claim one [src-bmj-2024]. Claim two [src-a][src-b]. Not a cite [q-001]."
    assert common.CITATION_RE.findall(text) == ["src-bmj-2024", "src-a", "src-b"]
