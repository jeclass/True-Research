"""Wave orchestration (COMPREHENSIVE_RESEARCH_SPEC item 4). BREADTH maps the
seed tree; when it concludes the driver seeds DEPTH questions from the top
findings and keeps looping to re-investigate them before VERIFY/SYNTHESIZE.
These pin: deterministic top-N selection, idempotent seeding, the wave-field
transition, and that a normal (waves-off) run never enters DEPTH."""

import yaml

import driver
from src.runspace import Runspace
from src.settings import Settings
from src.sessions.depth import seed_depth_questions
from src.state import (
    FindingMeta,
    OpenQuestion,
    QuestionList,
    parse_questions,
    parse_run_meta,
)
from tests.conftest import BASE_CONFIG, only_run_dir


def _settings(tmp_path, depth_findings: int) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["secrets"] = {"ANTHROPIC_API_KEY": "sk-test", "OLLAMA_AUTH": "ollama"}
    raw["waves"] = {"enabled": True, "depth_findings": depth_findings}
    return Settings.model_validate(raw)


def _run_with_findings(tmp_path, confidences: dict[str, float]) -> Runspace:
    run = Runspace.create(tmp_path / "runs", "q", "general")
    qs = [
        OpenQuestion(id=qid, question=f"facet {qid}", priority=3, created_by="initializer")
        for qid in confidences
    ]
    run.save_questions(QuestionList(qs))
    for qid, conf in confidences.items():
        run.write_finding(
            f"{qid}-c01",
            FindingMeta(question_id=qid, source_ids=["src-x"], confidence=conf),
            f"finding for {qid}",
        )
    return run


def test_seed_depth_questions_picks_top_n_by_confidence(tmp_path):
    # 4 findings, depth_findings=2 -> deepen the two MOST confident (lead claims).
    run = _run_with_findings(tmp_path, {"q-001": 0.9, "q-002": 0.5, "q-003": 0.8, "q-004": 0.6})
    settings = _settings(tmp_path, depth_findings=2)

    n = seed_depth_questions(run, settings)
    assert n == 2

    qs = run.load_questions()
    depth = [q for q in qs.root if q.created_by == "depth"]
    assert {q.parent_id for q in depth} == {"q-001", "q-003"}     # top-2 by confidence
    assert all(q.status == "open" and q.priority == 2 for q in depth)
    assert all(q.depth == 1 for q in depth)                       # parent.depth(0) + 1
    assert all("cross-validate" in q.question.lower() for q in depth)
    run.release_lock()


def test_seed_depth_questions_is_idempotent(tmp_path):
    # A crash between seeding and the wave flip must not double-seed on resume.
    run = _run_with_findings(tmp_path, {"q-001": 0.9, "q-002": 0.8})
    settings = _settings(tmp_path, depth_findings=5)
    assert seed_depth_questions(run, settings) == 2
    assert seed_depth_questions(run, settings) == 0               # already deepened
    assert len([q for q in run.load_questions().root if q.created_by == "depth"]) == 2
    run.release_lock()


def test_seed_depth_questions_empty_when_no_findings(tmp_path):
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([]))
    assert seed_depth_questions(run, _settings(tmp_path, depth_findings=3)) == 0
    run.release_lock()


def test_seed_depth_skips_and_logs_when_parent_question_is_gone(tmp_path):
    # audit completeness gap: if a finding's parent question is absent from
    # open_questions.yaml (pruned/closed), the old bare-except fallback silently
    # seeded a useless, depth-RESET question (text = the raw id, depth = 1 — losing
    # the tree bound). It must instead skip + log loudly (invariant 8).
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([
        OpenQuestion(id="q-present", question="facet present", priority=3,
                     created_by="initializer"),
    ]))
    run.write_finding("q-present-c01",
                      FindingMeta(question_id="q-present", source_ids=["src-x"], confidence=0.9),
                      "finding for present")
    run.write_finding("q-gone-c01",   # higher confidence -> sorted first, hits the orphan path
                      FindingMeta(question_id="q-gone", source_ids=["src-x"], confidence=0.95),
                      "finding whose parent question was pruned")

    n = seed_depth_questions(run, _settings(tmp_path, depth_findings=5))
    assert n == 1   # only the present-parent finding got a depth question; orphan skipped
    depth = [q for q in run.load_questions().root if q.created_by == "depth"]
    assert {q.parent_id for q in depth} == {"q-present"}
    progress = (run.root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "q-gone" in progress and "no longer in open_questions.yaml" in progress
    run.release_lock()


def _meta(run_dir):
    return parse_run_meta((run_dir / "run.json").read_text())


def test_waves_on_breadth_concludes_into_depth(make_config, runs_dir):
    # 2 seed questions resolve (BREADTH) -> driver seeds 2 DEPTH questions and
    # deepens them -> finishes conclusive in the DEPTH wave.
    cfg = make_config(**{
        "stub.seed_questions": 2,
        "waves.enabled": True,
        "waves.depth_findings": 2,
    })
    rc = driver.main(["q", "--config", str(cfg), "--max-cycles", "12"])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    meta = _meta(run_dir)
    assert meta.finish_reason == "conclusive"
    assert meta.wave == "depth"                                   # advanced past BREADTH

    qs = parse_questions((run_dir / "open_questions.yaml").read_text())
    depth = [q for q in qs.root if q.created_by == "depth"]
    assert len(depth) == 2                                        # bounded by depth_findings
    assert all(q.parent_id in {"q-001", "q-002"} for q in depth)
    assert all(q.status == "resolved" for q in depth)            # deepened, then resolved

    progress = (run_dir / "PROGRESS.md").read_text()
    assert "BREADTH concluded; entering DEPTH wave" in progress


def test_waves_flag_enables_independent_of_comprehensive():
    from src.settings import load_settings

    assert not load_settings().waves.enabled               # off by default
    assert load_settings(overrides={"waves": True}).waves.enabled
    assert load_settings(overrides={"comprehensive": True}).waves.enabled  # implied


def test_waves_off_never_enters_depth(make_config, runs_dir):
    # The guard: a normal run never seeds depth questions or leaves BREADTH.
    cfg = make_config(**{"stub.seed_questions": 2})  # waves.enabled defaults False
    rc = driver.main(["q", "--config", str(cfg), "--max-cycles", "12"])
    assert rc == 0

    run_dir = only_run_dir(runs_dir)
    assert _meta(run_dir).wave == "breadth"
    qs = parse_questions((run_dir / "open_questions.yaml").read_text())
    assert not [q for q in qs.root if q.created_by == "depth"]
