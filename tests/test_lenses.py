"""Community lens (docs/COMMUNITY_LENS_SPEC.md): the orthogonal evidence axis.
Covers state track defaults, the lens registry, settings validation, the
track-filtered findings digest, the initializer seeding, and — the load-bearing
property — that community findings are quarantined out of the factual
synthesizer's context and appended into their own report section."""

from pathlib import Path

import pytest
import yaml

from src.errors import ConfigError
from src.ledger import Ledger
from src.lenses import available_lenses, get_lens, lens_for_track
from src.runspace import Runspace
from src.sessions import common, synthesizer
from src.settings import Settings
from src.state import FindingMeta, OpenQuestion, QuestionList
from tests.conftest import BASE_CONFIG


def _settings(tmp_path: Path, **overrides) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw.setdefault("secrets", {"ANTHROPIC_API_KEY": "sk-test", "OLLAMA_AUTH": "ollama"})
    for dotted, value in overrides.items():
        node = raw
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return Settings.model_validate(raw)


@pytest.fixture
def run(tmp_path: Path) -> Runspace:
    r = Runspace.create(tmp_path / "runs", "do robot vacuums actually last?", "general")
    yield r
    r.release_lock()


# --- state + registry ---------------------------------------------------------


def test_question_and_finding_default_to_factual_track():
    q = OpenQuestion(id="q-001", question="x", priority=3, created_by="initializer")
    assert q.track == "factual"
    m = FindingMeta(question_id="q-001", source_ids=["src-a"], confidence=0.5)
    assert m.track == "factual"


def test_lens_registry_resolves_community():
    assert "community" in available_lenses()
    lens = get_lens("community")
    assert lens.track() == "community"
    assert lens.seed_questions("q?")  # at least one seed
    assert lens.report_section_title()
    assert lens.report_section_framing()


def test_get_lens_unknown_raises():
    with pytest.raises(ConfigError, match="unknown lens"):
        get_lens("nope")


def test_lens_for_track_only_matches_active():
    assert lens_for_track("community", ["community"]).name == "community"
    assert lens_for_track("community", []) is None
    assert lens_for_track("factual", ["community"]) is None


# --- settings validation ------------------------------------------------------


def test_settings_accepts_known_lens_rejects_unknown(tmp_path):
    assert _settings(tmp_path, lenses=["community"]).lenses == ["community"]
    with pytest.raises(Exception, match="unknown lens"):
        _settings(tmp_path, lenses=["bogus"])


def test_default_settings_have_no_lenses(tmp_path):
    assert _settings(tmp_path).lenses == []


# --- findings digest track filter ---------------------------------------------


def test_findings_digest_only_tracks_filters(run):
    run.write_finding("q-001-c01",
                      FindingMeta(question_id="q-001", source_ids=["src-a"], confidence=0.8,
                                  track="factual"), "Factual body [src-a].")
    run.write_finding("q-002-c01",
                      FindingMeta(question_id="q-002", source_ids=["src-b"], confidence=0.6,
                                  track="community"), "Community body [src-b].")
    all_d = common.findings_digest(run, full_bodies=True)
    factual_d = common.findings_digest(run, full_bodies=True, only_tracks={"factual"})
    assert "Factual body" in all_d and "Community body" in all_d
    assert "Factual body" in factual_d and "Community body" not in factual_d


# --- synthesizer quarantine (the load-bearing property) -----------------------


def _seed_sources(run):
    from src.state import SourceRecord, SourceRegistry

    reg = SourceRegistry({})
    for sid, url in (("src-fact", "https://journal.example/study"),
                     ("src-comm", "https://reddit.com/r/x/abc")):
        reg.root[sid] = SourceRecord(url=url, title="t", kind="web", credibility=50,
                                     retrieved_at=common.utcnow(), notes="")
    run.save_sources(reg)


def test_community_findings_quarantined_and_appended(run, tmp_path, monkeypatch):
    settings = _settings(tmp_path, lenses=["community"])
    run.mark_finishing("conclusive")
    _seed_sources(run)
    run.write_finding("q-001-c01",
                      FindingMeta(question_id="q-001", source_ids=["src-fact"], confidence=0.8,
                                  track="factual"), "Vacuums last ~5 years [src-fact].")
    run.write_finding("q-009-c01",
                      FindingMeta(question_id="q-009", source_ids=["src-comm"], confidence=0.5,
                                  track="community"), "Owners on r/x say belts wear out [src-comm].")

    captured = {}

    class _Spawn:
        structured = type("O", (), {"report_markdown": "# Report\n\nVacuums last ~5 years [src-fact]."})()
        input_tokens = output_tokens = cached_tokens = 1
        usd = 0.0
        wall_seconds = 0.1
        num_turns = 1

    def fake_session(**kw):
        captured["prompt"] = kw["user_prompt"]
        return _Spawn()

    monkeypatch.setattr(synthesizer, "run_role_session", fake_session)
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    # The factual model NEVER saw the community finding:
    assert "belts wear out" not in captured["prompt"]
    assert "Vacuums last ~5 years" in captured["prompt"]
    # The report has BOTH the factual body and the quarantined community section:
    assert "Vacuums last ~5 years [src-fact]" in report
    assert "Community & practitioner perspective" in report
    assert "belts wear out [src-comm]" in report
    assert "sentiment and anecdote" in report  # the framing caveat


def test_synthesizer_no_community_section_when_none(run, tmp_path, monkeypatch):
    settings = _settings(tmp_path)  # no lenses
    run.mark_finishing("conclusive")
    _seed_sources(run)
    run.write_finding("q-001-c01",
                      FindingMeta(question_id="q-001", source_ids=["src-fact"], confidence=0.8),
                      "Vacuums last ~5 years [src-fact].")

    class _Spawn:
        structured = type("O", (), {"report_markdown": "# Report\n\nVacuums last ~5 years [src-fact]."})()
        input_tokens = output_tokens = cached_tokens = 1
        usd = 0.0
        wall_seconds = 0.1
        num_turns = 1

    monkeypatch.setattr(synthesizer, "run_role_session", lambda **kw: _Spawn())
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))
    report = (run.root / "REPORT.md").read_text(encoding="utf-8")
    assert "Community & practitioner perspective" not in report


def _fake_synth_session():
    class _Spawn:
        structured = type("O", (), {"report_markdown": "# Report\n\nVacuums last ~5 years [src-fact]."})()
        input_tokens = output_tokens = cached_tokens = 1
        usd = 0.0
        wall_seconds = 0.1
        num_turns = 1

    return _Spawn()


def test_synthesizer_emits_pdf_next_to_report(run, tmp_path, monkeypatch):
    # audit #13: settings.emit_pdf defaults True and the synthesizer hook renders
    # REPORT.pdf next to REPORT.md, but 4+ synthesizer.run() tests exercised it as
    # a silent side effect with NO assertion — reverting the emit hook entirely
    # would pass the suite. Assert the artifact is actually written and is a real
    # PDF (the render_markdown_pdf unit tests cover the renderer; this covers the
    # integration point).
    settings = _settings(tmp_path)  # emit_pdf defaults True
    run.mark_finishing("conclusive")
    _seed_sources(run)
    run.write_finding("q-001-c01",
                      FindingMeta(question_id="q-001", source_ids=["src-fact"], confidence=0.8),
                      "Vacuums last ~5 years [src-fact].")

    monkeypatch.setattr(synthesizer, "run_role_session", lambda **kw: _fake_synth_session())
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    pdf = run.root / "REPORT.pdf"
    assert pdf.is_file()
    assert pdf.read_bytes()[:5] == b"%PDF-"   # a real PDF, not an empty/garbage file


def test_synthesizer_pdf_failure_is_logged_decision_not_a_crash(run, tmp_path, monkeypatch):
    # audit #13 + invariant 8: a PDF render failure (missing dep / bad path) must
    # be a logged DECISION, never a crash — REPORT.md is the source of truth and is
    # already on disk. Force the renderer to fail and assert the run still finishes
    # with REPORT.md intact and the failure recorded in the DECISIONS log.
    import src.tools.report_pdf as report_pdf

    settings = _settings(tmp_path)
    run.mark_finishing("conclusive")
    _seed_sources(run)
    run.write_finding("q-001-c01",
                      FindingMeta(question_id="q-001", source_ids=["src-fact"], confidence=0.8),
                      "Vacuums last ~5 years [src-fact].")

    # synthesizer does `from src.tools.report_pdf import render_markdown_pdf` at call
    # time, so patch the source module attribute the late import resolves.
    monkeypatch.setattr(report_pdf, "render_markdown_pdf",
                        lambda md, path: (False, "forced failure for test"))
    monkeypatch.setattr(synthesizer, "run_role_session", lambda **kw: _fake_synth_session())
    synthesizer.run(run, settings, cycle=1, ledger=Ledger(run))

    assert (run.root / "REPORT.md").read_text(encoding="utf-8")   # report intact
    assert not (run.root / "REPORT.pdf").exists()                 # no bogus PDF written
    progress = (run.root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "REPORT.pdf not generated" in progress                # logged as a DECISION
