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
