"""Verification wave (docs/COMPREHENSIVE_RESEARCH_SPEC.md §3): the engine-built
report section + the driver phase, with the verifier mocked. Zero LLM."""

from pathlib import Path

import yaml
from rich.console import Console

import driver
from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import synthesizer
from src.settings import Settings
from src.state import FindingMeta
from tests.conftest import BASE_CONFIG


def _settings(tmp_path: Path, **dotted) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw.setdefault("secrets", {})
    for key, value in dotted.items():
        node = raw
        *parents, leaf = key.split(".")
        for parent in parents:
            node = node[parent]
        node[leaf] = value
    return Settings.model_validate(raw)


def _finding(slug, status="unverified", note="", conf=0.8, track="factual"):
    meta = FindingMeta(
        question_id="q-001", source_ids=["src-a"], confidence=conf, track=track,
        verification_status=status, verification_note=note,
    )
    return meta, f"Body of {slug} [src-a]."


def test_verification_section_lists_refuted_and_counts():
    factual = {
        "f1": _finding("f1", "verified"),
        "f2": _finding("f2", "refuted", "contradicted by a 2024 RCT"),
        "f3": _finding("f3", "unverified"),
    }
    sec = synthesizer._verification_section(factual)
    assert "## Verification" in sec
    assert "1 survived" in sec and "1 were" in sec
    assert "f2" in sec and "contradicted by a 2024 RCT" in sec
    assert "f3" not in sec  # unverified findings are not listed


def test_verification_section_empty_when_nothing_checked():
    assert synthesizer._verification_section({"f1": _finding("f1", "unverified")}) == ""


def test_verify_phase_noop_when_disabled(tmp_path, monkeypatch):
    s = _settings(tmp_path)  # verification.enabled = False
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("f1", *_finding("f1"))
    import src.sessions.verifier as v

    calls = {"n": 0}
    monkeypatch.setattr(v, "verify_finding", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    driver._verify_phase(run, s, Ledger(run), Console())
    assert calls["n"] == 0
    run.release_lock()


def test_verify_phase_writes_status_and_respects_min_confidence(tmp_path, monkeypatch):
    s = _settings(tmp_path, **{"verification.enabled": True, "session.backend": "sdk"})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("f1", *_finding("f1", conf=0.9))   # load-bearing
    run.write_finding("f2", *_finding("f2", conf=0.3))   # below min_confidence 0.6
    import src.sessions.verifier as v

    monkeypatch.setattr(v, "verify_finding", lambda *a, **k: ("refuted", "independent check contradicts it"))
    driver._verify_phase(run, s, Ledger(run), Console())
    fs = run.load_findings()
    assert fs["f1"][0].verification_status == "refuted"
    assert fs["f1"][0].verification_note == "independent check contradicts it"
    assert fs["f2"][0].verification_status == "unverified"  # skipped (low confidence)
    run.release_lock()


def test_verify_phase_stops_at_budget(tmp_path, monkeypatch):
    s = _settings(tmp_path, **{"verification.enabled": True, "session.backend": "sdk",
                               "max_budget_usd": 0.0})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("f1", *_finding("f1", conf=0.9))
    import src.sessions.verifier as v

    calls = {"n": 0}
    monkeypatch.setattr(v, "verify_finding",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), ("verified", "")) [1])
    driver._verify_phase(run, s, Ledger(run), Console())
    assert calls["n"] == 0  # budget 0 => halted before any verify
    assert any("budget breaker" in d for d in run.decisions())
    run.release_lock()


def test_verify_risk_first_targets_single_source_over_high_confidence(tmp_path, monkeypatch):
    # roadmap: with risk_first (default on) a FIXED verifier budget refutes the
    # riskiest claim — a high-confidence SINGLE-source finding — BEFORE one at even
    # higher confidence that is already corroborated by several sources (lower
    # refutation leverage). The old confidence-first order would verify the
    # multi-source one first and, at budget 1, skip the under-corroborated claim.
    s = _settings(tmp_path, **{"verification.enabled": True, "session.backend": "sdk",
                               "verification.max_findings": 1})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("multi", FindingMeta(question_id="q-001",
        source_ids=["src-a", "src-b", "src-c"], confidence=0.95), "Body [src-a].")
    run.write_finding("single", FindingMeta(question_id="q-002",
        source_ids=["src-a"], confidence=0.85), "Body [src-a].")
    import src.sessions.verifier as v

    verified: list[str] = []
    monkeypatch.setattr(v, "verify_finding",
                        lambda *a, **k: (verified.append(a[5]), ("verified", ""))[1])
    driver._verify_phase(run, s, Ledger(run), Console())
    assert verified == ["single"]   # the single-source claim got the one budget slot
    run.release_lock()


def test_verify_skip_corroborated_excludes_multi_source(tmp_path, monkeypatch):
    # opt-in spend cut: skip_corroborated_min_sources=2 excludes a finding already
    # backed by >= 2 sources (cross-validated), focusing the verifier on the
    # single-source claim where an undetected error would hide.
    s = _settings(tmp_path, **{"verification.enabled": True, "session.backend": "sdk",
                               "verification.skip_corroborated_min_sources": 2})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("multi", FindingMeta(question_id="q-001",
        source_ids=["src-a", "src-b"], confidence=0.9), "Body [src-a].")
    run.write_finding("single", FindingMeta(question_id="q-002",
        source_ids=["src-a"], confidence=0.9), "Body [src-a].")
    import src.sessions.verifier as v

    verified: list[str] = []
    monkeypatch.setattr(v, "verify_finding",
                        lambda *a, **k: (verified.append(a[5]), ("verified", ""))[1])
    driver._verify_phase(run, s, Ledger(run), Console())
    assert verified == ["single"]   # 2-source finding skipped, only single-source verified
    run.release_lock()


def test_verifier_challenge_reads_bypass_completed_cache(monkeypatch):
    # Refutation independence: the verifier's challenge reads must NOT consume
    # breadth-phase cached digests (a breadth-framed summary can legitimately
    # omit exactly what a refutation-framed read would extract, starving the
    # verdict of counter-evidence). verify_finding must pass
    # bypass_completed=True to every read_source call.
    from types import SimpleNamespace

    import src.sessions.verifier as v
    from src.sessions import reader as reader_mod

    captured: list[dict] = []

    async def fake_session(**kwargs):
        if kwargs["output_model"] is v.RefutationQueries:
            return SimpleNamespace(structured=v.RefutationQueries(queries=["q1"]))
        return SimpleNamespace(structured=v.Verdict(status="uncertain", note="thin"))

    async def fake_read_source(**kwargs):
        captured.append(kwargs)
        out = reader_mod.ReaderOutput(
            useful=True, title="T", kind="web", credibility=70,
            notes="", summary_markdown="body", key_quotes=[],
        )
        return out, None

    async def fake_gather(providers, queries, run):
        return [{"url": "https://challenge.org/x", "snippet": "sn"}]

    monkeypatch.setattr(v, "run_role_session_async", fake_session)
    monkeypatch.setattr(v, "_gather_results", fake_gather)
    monkeypatch.setattr(v, "_pipeline_cfg",
                        lambda s, p: {"max_reads": 2, "queries_per_question": 2,
                                      "rerank": False})
    monkeypatch.setattr(v, "select_urls",
                        lambda *a, **k: [{"url": "https://challenge.org/x",
                                          "snippet": "sn"}])
    monkeypatch.setattr(reader_mod, "read_source", fake_read_source)

    run = SimpleNamespace(log=lambda msg: None,
                          load_sources=lambda: SimpleNamespace(root={}))
    profile = SimpleNamespace(pipeline_search_providers=lambda s: [],
                              url_preferences=lambda: [])
    settings = SimpleNamespace(worker_pipeline=SimpleNamespace(rerank=False))
    meta = FindingMeta(question_id="q-001", source_ids=["src-a"], confidence=0.9)

    status, _note = v.verify_finding(run, settings, None, 1, profile, "f1",
                                     meta, "claim body")
    assert status == "unverified"                       # uncertain maps to unverified
    assert captured, "verifier never reached read_source"
    assert all(kw.get("bypass_completed") is True for kw in captured)
