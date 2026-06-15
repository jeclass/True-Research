"""Question-tree depth, bounds, and comprehensive promotion
(docs/COMPREHENSIVE_RESEARCH_SPEC.md item 2). Pure state machinery — zero LLM."""

from pathlib import Path

import yaml

from src.runspace import Runspace
from src.sessions import initializer
from src.sessions.worker import ChildQuestion, WorkerOutput, _apply_fragmented
from src.settings import Settings, load_settings
from src.state import OpenQuestion, QuestionList
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


def _frag(children: list[str], priorities: list[int] | None = None) -> WorkerOutput:
    priorities = priorities or [3] * len(children)
    return WorkerOutput(
        outcome="fragmented",
        child_questions=[
            ChildQuestion(question=c, priority=p)
            for c, p in zip(children, priorities)
        ],
        progress_note="frag",
    )


def _seed(run: Runspace, q: OpenQuestion) -> OpenQuestion:
    run.save_questions(QuestionList([q]))
    return run.load_questions().get(q.id)


def test_fragmentation_assigns_child_depth(tmp_path):
    s = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")
    target = _seed(
        run,
        OpenQuestion(id="q-001", question="broad", priority=4, created_by="initializer"),
    )  # depth 0
    _apply_fragmented(run, s, target, _frag(["child a", "child b"]))
    qs = run.load_questions()
    kids = [q for q in qs.root if q.parent_id == "q-001"]
    assert len(kids) == 2 and all(k.depth == 1 for k in kids)
    assert qs.get("q-001").status == "resolved"
    run.release_lock()


def test_depth_cap_refuses_and_leaves_a_leaf(tmp_path):
    s = _settings(tmp_path, **{"question_tree.max_depth": 2})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    target = _seed(
        run,
        OpenQuestion(id="q-001", question="deep", priority=3, created_by="worker", depth=2),
    )  # a child would be depth 3 > max_depth 2
    summary = _apply_fragmented(run, s, target, _frag(["would-be child"]))
    qs = run.load_questions()
    assert all(q.parent_id != "q-001" for q in qs.root)  # nothing created
    assert qs.get("q-001").status == "resolved"  # capped as a leaf
    assert "capped" in summary
    assert any("depth" in d and "REFUSED" in d for d in run.decisions())
    run.release_lock()


def test_node_cap_refuses_when_tree_full(tmp_path):
    s = _settings(tmp_path, **{"question_tree.max_questions": 3})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(
        QuestionList(
            [
                OpenQuestion(id="q-001", question="a", priority=3, created_by="initializer"),
                OpenQuestion(id="q-002", question="b", priority=3, created_by="initializer"),
            ]
        )
    )
    target = run.load_questions().get("q-001")
    # 2 existing + 2 proposed children = 4 > cap 3 -> refuse
    summary = _apply_fragmented(run, s, target, _frag(["c1", "c2"]))
    assert len(run.load_questions().root) == 2  # no children added
    assert "capped" in summary
    assert any("question cap" in d for d in run.decisions())
    run.release_lock()


def test_children_inherit_community_track(tmp_path):
    # A community-track question fragmenting must keep its children quarantined,
    # else forum inquiry leaks into the factual report.
    s = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")
    target = _seed(
        run,
        OpenQuestion(
            id="q-001", question="forum facet", priority=3,
            created_by="initializer", track="community",
        ),
    )
    _apply_fragmented(run, s, target, _frag(["sub forum a"]))
    kids = [q for q in run.load_questions().root if q.parent_id == "q-001"]
    assert kids and all(k.track == "community" for k in kids)
    run.release_lock()


def test_comprehensive_promotes_deep_bundle(tmp_path):
    cfg = tmp_path / "config.yaml"
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-test\nOLLAMA_AUTH=ollama\n", encoding="utf-8")

    base = load_settings(cfg, env)
    deep = load_settings(cfg, env, overrides={"comprehensive": True})
    comp = BASE_CONFIG["comprehensive"]
    assert base.max_cycles == BASE_CONFIG["max_cycles"]  # normal load unaffected
    assert deep.max_cycles == comp["max_cycles"]
    assert deep.question_tree.max_depth == comp["max_depth"]
    assert deep.question_tree.seed_target == comp["seed_target"]
    # an explicit CLI override still wins over the bundle
    win = load_settings(cfg, env, overrides={"comprehensive": True, "max_budget_usd": 7.0})
    assert win.max_budget_usd == 7.0


def test_evaluator_gap_inherits_depth_from_parent(tmp_path):
    # The fail-and-deepen loop is the engine's real depth mechanism (local
    # workers rarely fragment). A gap linked to a parent is one level deeper;
    # an unlinked top-level gap stays at 0.
    from src.sessions import evaluator

    s = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(
        QuestionList(
            [OpenQuestion(id="q-001", question="seed", priority=4, created_by="initializer")]
        )
    )

    def _gap(parent, text):
        return evaluator.EvaluatorOutput(
            passed=False, unmet_criteria=["gap"], contradictions=[],
            new_questions=[
                evaluator.ProposedQuestion(question=text, priority=3, parent_id=parent)
            ],
            close_questions=[], notes="n",
        )

    # distinct texts (the dedup guard drops verbatim repeats)
    evaluator._apply_output(run, _gap("q-001", "refine the seed with effect sizes"), 1, s)
    evaluator._apply_output(run, _gap(None, "a brand new top-level facet entirely"), 2, s)
    qs = run.load_questions()
    linked = [q for q in qs.root if q.parent_id == "q-001"]
    top = [q for q in qs.root if q.created_by == "evaluator" and q.parent_id is None]
    assert linked and linked[0].depth == 1
    assert top and top[0].depth == 0
    run.release_lock()


def test_initializer_prompt_scales_with_seed_target():
    normal = initializer.build_system_prompt(6)
    comp = initializer.build_system_prompt(12)
    assert "3 to 6" in normal and "COMPREHENSIVE" not in normal
    assert "12" in comp and "COMPREHENSIVE" in comp


def test_duplicate_question_detection():
    from src.sessions import common

    qs = QuestionList([
        OpenQuestion(
            id="q-001",
            question="What is the evidence for creatine's effect on cognition in healthy adults?",
            priority=3, created_by="initializer",
        )
    ])
    # verbatim, and near-verbatim (case/punctuation) => duplicate
    assert common.duplicate_question_id(
        "What is the evidence for creatine's effect on cognition in healthy adults?", qs
    ) == "q-001"
    assert common.duplicate_question_id(
        "what is the evidence for creatines effect on cognition in healthy adults", qs
    ) == "q-001"
    # genuinely different facet => not a duplicate
    assert common.duplicate_question_id(
        "What is the biochemical mechanism of creatine phosphorylation in muscle?", qs
    ) is None


def test_evaluator_drops_duplicate_gaps(tmp_path):
    # The core fix: local evaluator re-emits existing questions as "new"; the
    # engine must drop them (observed comprehensive run 2026-06-15).
    from src.sessions import evaluator

    s = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([
        OpenQuestion(id="q-001", question="Creatine effects on muscle strength and power output?",
                     priority=4, created_by="initializer"),
    ]))
    out = evaluator.EvaluatorOutput(
        passed=False, unmet_criteria=["x"], contradictions=[],
        new_questions=[
            evaluator.ProposedQuestion(question="Creatine effects on muscle strength and power output?", priority=3),
            evaluator.ProposedQuestion(question="Creatine effects on bone mineral density in older adults?", priority=3),
        ],
        close_questions=[], notes="n",
    )
    _p, _n, added, _c = evaluator._apply_output(run, out, 1, s)
    assert len(added) == 1  # only the genuinely-new gap survived
    run.release_lock()
