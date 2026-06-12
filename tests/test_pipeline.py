"""Pipeline-worker mode (docs/PIPELINE_WORKER_SPEC.md): pure selection/source
builders + the orchestrated flow with all model calls faked — zero LLM."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.errors import ConfigError
from src.ledger import Ledger
from src.profiles.base import Profile, WorkerToolContext, WorkerToolset
from src.runspace import Runspace
from src.sessions import pipeline
from src.sessions.base import ReaderError, WorkerError
from src.sessions.reader import ReaderOutput
from src.settings import Settings
from src.state import OpenQuestion, QuestionList
from tests.conftest import BASE_CONFIG

CFG = {"queries_per_question": 4, "urls_per_query": 4, "max_reads": 12, "per_domain_cap": 2}
NO_PREFS: dict[str, Any] = {"preferred_domains": [], "domain_cap_overrides": {}}


def _settings(tmp_path: Path, **overrides) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["secrets"] = {"ANTHROPIC_API_KEY": "sk-test", "OLLAMA_AUTH": "ollama"}
    raw["worker_pipeline"]["enabled"] = True
    raw["search"]["searxng_base_url"] = "http://localhost:8888"
    for dotted, value in overrides.items():
        node = raw
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return Settings.model_validate(raw)


def _r(url: str, title: str = "t") -> dict:
    return {"title": title, "url": url, "snippet": "s"}


# --- select_urls (pure) ----------------------------------------------------------


def test_select_urls_round_robin_and_caps():
    results = [
        [_r(f"https://a.com/{i}") for i in range(10)],
        [_r(f"https://b.com/{i}") for i in range(10)],
    ]
    cfg = dict(CFG, max_reads=4, per_domain_cap=2, urls_per_query=4)
    selected = pipeline.select_urls(results, set(), cfg, NO_PREFS)
    assert len(selected) == 4
    domains = [u["url"].split("/")[2] for u in selected]
    assert domains.count("a.com") == 2 and domains.count("b.com") == 2


def test_select_urls_skips_registry_and_dupes_and_non_http():
    results = [[
        _r("https://a.com/x"),
        _r("https://A.com/x/"),          # normalized dupe
        _r("ftp://weird"),               # non-http
        _r("https://already.org/seen"),  # in registry
        _r("https://b.com/y"),
    ]]
    selected = pipeline.select_urls(
        results, {"https://already.org/seen"}, dict(CFG), NO_PREFS
    )
    urls = [u["url"] for u in selected]
    assert urls == ["https://a.com/x", "https://b.com/y"]


def test_select_urls_preferred_domains_rank_first_with_cap_override():
    results = [[
        _r("https://random.com/1"),
        _r("https://pmc.ncbi.nlm.nih.gov/articles/PMC1"),
        _r("https://pmc.ncbi.nlm.nih.gov/articles/PMC2"),
        _r("https://pmc.ncbi.nlm.nih.gov/articles/PMC3"),
    ]]
    prefs = {
        "preferred_domains": ["pmc.ncbi.nlm.nih.gov"],
        "domain_cap_overrides": {"pmc.ncbi.nlm.nih.gov": 3},
    }
    selected = pipeline.select_urls(results, set(), dict(CFG, max_reads=4), prefs)
    assert [u["url"] for u in selected][:3] == [
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC2",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC3",
    ]
    assert selected[3]["url"] == "https://random.com/1"


def test_select_urls_per_query_cap():
    results = [[_r(f"https://q0-{i}.com/") for i in range(6)], []]
    selected = pipeline.select_urls(
        results, set(), dict(CFG, urls_per_query=3, max_reads=12), NO_PREFS
    )
    assert len(selected) == 3


# --- engine-built sources ------------------------------------------------------------


def _ro(title: str, credibility: int = 80, kind: str = "web") -> ReaderOutput:
    return ReaderOutput(useful=True, title=title, kind=kind, credibility=credibility,
                        notes="n", summary_markdown="facts")


def test_build_engine_sources_slugs_and_dedupes():
    from src.sessions.common import SOURCE_ID_RE

    reads = [
        ("https://a.com/1", _ro("BMJ Meta-Analysis 2024!")),
        ("https://a.com/2", _ro("BMJ Meta-Analysis 2024!")),  # same title
        ("https://b.com/3", _ro("Étude Sundfør——2018")),       # non-ascii
    ]
    sources = pipeline.build_engine_sources(reads)
    ids = [s["id"] for s in sources]
    assert len(set(ids)) == 3
    assert ids[0] == "src-bmj-meta-analysis-2024"
    assert ids[1] == "src-bmj-meta-analysis-2024-2"
    for s in sources:
        assert SOURCE_ID_RE.match(s["id"]), s["id"]
        assert s["url"].startswith("http")


def test_pipeline_cfg_profile_overrides(tmp_path):
    from src.profiles import get_profile

    settings = _settings(tmp_path)
    cfg = pipeline._pipeline_cfg(settings, get_profile("scientific"))
    assert cfg["queries_per_question"] == 5 and cfg["max_reads"] == 16
    assert cfg["urls_per_query"] == 4  # untouched default


def test_visual_profile_refuses_pipeline(tmp_path):
    from src.profiles import get_profile

    with pytest.raises(ConfigError, match="agentic worker"):
        get_profile("visual").pipeline_search_providers(_settings(tmp_path))


def test_general_profile_requires_searxng(tmp_path):
    from src.profiles import get_profile

    settings = _settings(tmp_path, **{"search.searxng_base_url": None})
    with pytest.raises(ConfigError, match="searxng_base_url"):
        get_profile("general").pipeline_search_providers(settings)


# --- orchestrated flow (all model calls faked) -----------------------------------------


@dataclass
class FakeSpawn:
    structured: Any
    input_tokens: int = 10
    output_tokens: int = 5
    cached_tokens: int = 0
    usd: float = 0.0
    wall_seconds: float = 0.1
    num_turns: int = 1
    result_text: str = ""


class FakeProfile(Profile):
    name = "general"

    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def pipeline_search_providers(self, settings):
        async def provider(query: str):
            return list(self._results)

        return [("fake", provider)]

    def worker_toolset(self, ctx: WorkerToolContext) -> WorkerToolset:  # pragma: no cover
        return WorkerToolset(builtin=[])

    def rubric(self) -> str:
        return "r"

    def worker_guidance(self) -> str:
        return "g"


@pytest.fixture
def run_env(tmp_path):
    settings = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "overall q", "general")
    run.write_text("PLAN.md", "# plan\n")
    target = OpenQuestion(id="q-001", question="assigned?", priority=5,
                          created_by="initializer", status="in_progress")
    run.save_questions(QuestionList([target]))
    yield run, settings, target
    run.release_lock()


def test_pipeline_happy_path_resolves_with_engine_sources(run_env, monkeypatch):
    run, settings, target = run_env
    sessions = {"n": 0}

    async def fake_session(**kwargs):
        sessions["n"] += 1
        if kwargs["output_model"] is pipeline.QueryGenOutput:
            return FakeSpawn(pipeline.QueryGenOutput(queries=["q one", "q two"], notes="n"))
        # compose: two-part text format, citing the first menu id verbatim
        menu_id = kwargs["user_prompt"].split("[", 1)[1].split("]", 1)[0]
        return FakeSpawn(None, result_text=(
            '{"outcome": "resolved", "confidence": 0.8, "child_questions": [],'
            ' "blocked_reason": "", "progress_note": "composed"}\n'
            f"---FINDING---\nA composed claim. [{menu_id}]"
        ))

    async def fake_read(*, url, **kwargs):
        return _ro(f"Title for {url.split('//')[1]}"), FakeSpawn(None)

    monkeypatch.setattr(pipeline, "run_role_session_async", fake_session)
    monkeypatch.setattr(pipeline.reader, "read_source", fake_read)

    profile = FakeProfile([_r("https://a.com/1"), _r("https://b.com/2")])
    result = pipeline.run_pipeline(run, settings, 1, Ledger(run), target, profile)

    assert "resolved q-001" in result.summary and "pipeline:" in result.summary
    assert sessions["n"] == 2  # query-gen + compose, nothing else
    questions = run.load_questions()
    assert questions.get("q-001").status == "resolved"
    registry = run.load_sources()
    assert len(registry.root) == 2  # engine-built, both read URLs registered
    findings = run.load_findings()
    assert len(findings) == 1
    meta, body = next(iter(findings.values()))
    assert meta.source_ids[0] in registry.root and "[src-" in body


def test_pipeline_blocks_without_compose_when_no_useful_reads(run_env, monkeypatch):
    run, settings, target = run_env
    sessions = {"n": 0}

    async def fake_session(**kwargs):
        sessions["n"] += 1
        return FakeSpawn(pipeline.QueryGenOutput(queries=["q"], notes="n"))

    async def fake_read(*, url, **kwargs):
        raise ReaderError(f"fetch failed for {url}")

    monkeypatch.setattr(pipeline, "run_role_session_async", fake_session)
    monkeypatch.setattr(pipeline.reader, "read_source", fake_read)

    profile = FakeProfile([_r("https://a.com/1")])
    result = pipeline.run_pipeline(run, settings, 1, Ledger(run), target, profile)

    assert "blocked" in result.summary
    assert sessions["n"] == 1  # query-gen only — compose never paid for
    assert run.load_questions().get("q-001").status == "open"
    assert any("engine-blocked without compose" in d for d in run.decisions())


def test_pipeline_compose_citing_off_menu_id_fails_loudly(run_env, monkeypatch):
    run, settings, target = run_env

    async def fake_session(**kwargs):
        if kwargs["output_model"] is pipeline.QueryGenOutput:
            return FakeSpawn(pipeline.QueryGenOutput(queries=["q"], notes="n"))
        return FakeSpawn(None, result_text=(
            '{"outcome": "resolved", "confidence": 0.9, "child_questions": [],'
            ' "blocked_reason": "", "progress_note": "bad"}\n'
            "---FINDING---\nClaim. [src-invented-id]"
        ))

    async def fake_read(*, url, **kwargs):
        return _ro("Real Title"), FakeSpawn(None)

    monkeypatch.setattr(pipeline, "run_role_session_async", fake_session)
    monkeypatch.setattr(pipeline.reader, "read_source", fake_read)

    profile = FakeProfile([_r("https://a.com/1")])
    with pytest.raises(WorkerError, match="src-invented-id"):
        pipeline.run_pipeline(run, settings, 1, Ledger(run), target, profile)


def test_worker_run_branches_to_pipeline_when_enabled(run_env, monkeypatch):
    from src.sessions import worker as worker_mod
    from src.sessions.base import SessionResult

    run, settings, target = run_env
    # reset target to open so worker selection picks it
    questions = run.load_questions()
    questions.get("q-001").status = "open"
    run.save_questions(questions)

    called = {}

    def fake_pipeline(run_, settings_, cycle, ledger, target_, profile):
        called["target"] = target_.id
        return SessionResult(
            session_type="worker", model="m", endpoint="local",
            input_tokens=0, output_tokens=0, cached_tokens=0, usd=0.0,
            wall_seconds=0.1, summary="pipeline ran",
        )

    monkeypatch.setattr("src.sessions.pipeline.run_pipeline", fake_pipeline)
    result = worker_mod.run(run, settings, 1, Ledger(run))
    assert called["target"] == "q-001" and result.summary == "pipeline ran"
    # selection marked it in_progress before the pipeline took over
    assert run.load_questions().get("q-001").status == "in_progress"


def test_compose_output_migrates_progress_note_nested_in_finding():
    # Observed on qwen3.5-9b-32k (smoke 2026-06-10): valid content, but
    # progress_note nested inside finding instead of top-level.
    out = pipeline.ComposeOutput.model_validate(
        {
            "outcome": "resolved",
            "finding": {
                "body_markdown": "Degradation is ~1.8%/yr [src-a].",
                "confidence": 0.8,
                "progress_note": "Synthesized capacity degradation finding.",
            },
            "blocked_reason": "",
        }
    )
    assert out.progress_note == "Synthesized capacity degradation finding."
    assert out.finding is not None
    assert out.finding.body_markdown.startswith("Degradation")


def test_compose_output_does_not_clobber_existing_top_level():
    out = pipeline.ComposeOutput.model_validate(
        {
            "outcome": "blocked",
            "finding": None,
            "blocked_reason": "summaries insufficient",
            "progress_note": "top-level wins",
        }
    )
    assert out.progress_note == "top-level wins"


@pytest.mark.anyio
async def test_single_shot_retries_parse_failures(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")
    calls = {"n": 0}

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise WorkerError("worker session did not return parseable JSON - x")
        return "spawn-ok"

    monkeypatch.setattr(pipeline, "run_role_session_async", flaky)
    result = await pipeline._single_shot_with_retry(
        "compose", run=run, settings=settings, ledger=Ledger(run), cycle=1,
    )
    assert result == "spawn-ok"
    assert calls["n"] == 3
    run.release_lock()


@pytest.mark.anyio
async def test_single_shot_exhausts_then_raises(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")

    async def always_bad(**kw):
        raise WorkerError("structured output failed validation: y")

    monkeypatch.setattr(pipeline, "run_role_session_async", always_bad)
    with pytest.raises(WorkerError):
        await pipeline._single_shot_with_retry(
            "query-gen", run=run, settings=settings, ledger=Ledger(run), cycle=1,
        )
    run.release_lock()


@pytest.mark.anyio
async def test_single_shot_does_not_retry_other_errors(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "q", "general")
    calls = {"n": 0}

    async def transport_dead(**kw):
        calls["n"] += 1
        raise WorkerError("session wall-timeout exceeded")

    monkeypatch.setattr(pipeline, "run_role_session_async", transport_dead)
    with pytest.raises(WorkerError):
        await pipeline._single_shot_with_retry(
            "compose", run=run, settings=settings, ledger=Ledger(run), cycle=1,
        )
    assert calls["n"] == 1
    run.release_lock()


def test_engine_sources_unique_against_existing_registry():
    # Observed smoke3 2026-06-10: two different domains with the same generic
    # SEO title collided across cycles. The builder must consult the registry.
    from src.state import SourceRegistry

    reg = SourceRegistry.model_validate(
        {
            "src-how-long-do-electric-car-batteries-l": {
                "url": "https://www.geotab.com/blog/ev-battery-health/",
                "title": "How Long Do Electric Car Batteries Last?",
                "kind": "web",
                "credibility": 70,
                "retrieved_at": "2026-06-10T00:00:00+00:00",
                "notes": "",
            }
        }
    )
    out = ReaderOutput(
        useful=True,
        title="How Long Do Electric Car Batteries Last?",
        kind="web",
        credibility=60,
        notes="",
        summary_markdown="x",
    )
    built = pipeline.build_engine_sources(
        [("https://coltura.org/electric-car-battery-life/", out)], reg
    )
    assert built[0]["id"] != "src-how-long-do-electric-car-batteries-l"
    assert built[0]["url"] == "https://coltura.org/electric-car-battery-life/"


def test_engine_sources_reuse_id_for_registered_url():
    from src.state import SourceRegistry

    reg = SourceRegistry.model_validate(
        {
            "src-geotab-ev": {
                "url": "https://www.geotab.com/blog/ev-battery-health/",
                "title": "EV Battery Health",
                "kind": "web",
                "credibility": 70,
                "retrieved_at": "2026-06-10T00:00:00+00:00",
                "notes": "",
            }
        }
    )
    out = ReaderOutput(
        useful=True, title="EV Battery Health (updated)", kind="web",
        credibility=72, notes="", summary_markdown="y",
    )
    built = pipeline.build_engine_sources(
        [("https://www.geotab.com/blog/ev-battery-health/", out)], reg
    )
    assert built[0]["id"] == "src-geotab-ev"


def test_parse_compose_two_part_resolved_with_hostile_body():
    # The killer case that motivated the format: markdown bodies full of
    # braces, quotes, and newlines must not touch any JSON string.
    text = (
        "```json\n"
        '{"outcome": "resolved", "confidence": 0.8, "child_questions": [],\n'
        ' "blocked_reason": "", "progress_note": "synthesized"}\n'
        "```\n"
        "---FINDING---\n"
        'Degradation is ~1.8%/yr [src-a]. The study notes {"raw": "json"} and\n'
        "unbalanced } braces { plus \"quotes\" everywhere [src-b].\n"
    )
    out = pipeline.parse_compose_output(text)
    assert out.outcome == "resolved"
    assert out.finding.confidence == 0.8
    assert "unbalanced } braces {" in out.finding.body_markdown
    assert out.progress_note == "synthesized"


def test_parse_compose_blocked_needs_no_body():
    text = (
        '{"outcome": "blocked", "child_questions": [], '
        '"blocked_reason": "summaries insufficient", "progress_note": "n"}'
    )
    out = pipeline.parse_compose_output(text)
    assert out.outcome == "blocked"
    assert out.finding is None


def test_parse_compose_resolved_without_body_raises():
    text = (
        '{"outcome": "resolved", "confidence": 0.9, "child_questions": [], '
        '"blocked_reason": "", "progress_note": "n"}'
    )
    with pytest.raises(ValueError):
        pipeline.parse_compose_output(text)


def test_parse_compose_resolved_without_confidence_raises():
    text = (
        '{"outcome": "resolved", "child_questions": [], "blocked_reason": "", '
        '"progress_note": "n"}\n---FINDING---\nBody [src-a].'
    )
    with pytest.raises(ValueError):
        pipeline.parse_compose_output(text)


def test_select_urls_filters_blocked_domains():
    results = [[
        {"url": "https://www.facebook.com/groups/x/posts/1/", "snippet": "s"},
        {"url": "https://m.youtube.com/watch?v=abc", "snippet": "s"},
        {"url": "https://example-paywall.com/article", "snippet": "s"},
        {"url": "https://geotab.com/blog/ev/", "snippet": "s"},
    ]]
    selected = pipeline.select_urls(
        results, set(), CFG,
        {"preferred_domains": [], "domain_cap_overrides": {},
         "blocked_domains": ["example-paywall.com"]},
    )
    urls = [s["url"] for s in selected]
    assert urls == ["https://geotab.com/blog/ev/"]


def test_parse_compose_blocked_without_progress_note_derives_one():
    # Observed smoke9 p2 2026-06-10: an honest blocked outcome rerolled to
    # death because the model put its explanation in blocked_reason and
    # omitted progress_note. Derivable fields must not kill a roll.
    text = (
        '{"outcome": "blocked", "child_questions": [], '
        '"blocked_reason": "thin sources for capacity-fade linearity"}'
    )
    out = pipeline.parse_compose_output(text)
    assert out.outcome == "blocked"
    assert "thin sources" in out.progress_note


def test_parse_compose_rejects_off_menu_citations_for_reroll():
    # Observed smoke10 2026-06-10: a wholly hallucinated id (ceramic kilns in
    # an EV question) passed parsing and died at apply, outside the reroll
    # net. Menu validation now happens inside the retried parse.
    text = (
        '{"outcome": "resolved", "confidence": 0.8, "child_questions": [], '
        '"blocked_reason": "", "progress_note": "n"}\n'
        "---FINDING---\nClaim [src-real]. Fabricated claim [src-invented]."
    )
    with pytest.raises(ValueError, match="src-invented"):
        pipeline.parse_compose_output(text, {"src-real"})
    out = pipeline.parse_compose_output(
        '{"outcome": "resolved", "confidence": 0.8, "child_questions": [], '
        '"blocked_reason": "", "progress_note": "n"}\n'
        "---FINDING---\nClaim [src-real].",
        {"src-real"},
    )
    assert out.finding is not None


def test_build_engine_sources_derives_title_for_untitled_pages():
    # Observed smoke14 2026-06-11: empty reader title -> SourceRecord
    # validation death. Title falls back to domain+path.
    out = ReaderOutput(useful=True, title="", kind="web", credibility=50,
                       notes="n", summary_markdown="s")
    sources = pipeline.build_engine_sources([("https://example.com/page-x", out)])
    assert sources[0]["title"].startswith("example.com")
    assert sources[0]["id"].startswith("src-example-com")


def test_select_urls_relevance_outranks_authority_when_reranked():
    # Two candidates: a high-authority page that's off-topic, and a blog that's
    # a bull's-eye. With reranking, the bull's-eye is read first.
    results = [[
        {"url": "https://stanford.edu/unrelated-page", "title": "campus map", "snippet": "directions"},
        {"url": "https://someblog.com/ev-degradation", "title": "EV battery fade rates", "snippet": "1.8%/yr"},
    ]]
    prefs = {"preferred_domains": ["edu"], "domain_cap_overrides": {}}
    cfg = {"queries_per_question": 4, "urls_per_query": 4, "max_reads": 2, "per_domain_cap": 2}

    def fake_rerank(question, items):
        return {pipeline.common.normalize_url(it["url"]):
                (0.9 if "ev-degradation" in it["url"] else 0.01) for it in items}

    out = pipeline.select_urls(results, set(), cfg, prefs,
                               question="EV battery degradation rate",
                               rerank_fn=fake_rerank)
    assert "ev-degradation" in out[0]["url"]  # bull's-eye first despite blog domain


def test_select_urls_without_reranker_is_authority_first():
    # No reranker -> identical to prior behavior (edu domain first).
    results = [[
        {"url": "https://someblog.com/x", "title": "x", "snippet": "x"},
        {"url": "https://stanford.edu/y", "title": "y", "snippet": "y"},
    ]]
    prefs = {"preferred_domains": ["edu"], "domain_cap_overrides": {}}
    cfg = {"queries_per_question": 4, "urls_per_query": 4, "max_reads": 2, "per_domain_cap": 2}
    out = pipeline.select_urls(results, set(), cfg, prefs)
    assert "stanford.edu" in out[0]["url"]


def test_rerank_scores_empty_when_reranker_unavailable(monkeypatch):
    monkeypatch.setattr(pipeline, "_get_reranker", lambda: None)
    assert pipeline.rerank_scores("q", [{"url": "https://x.com", "title": "t", "snippet": "s"}]) == {}


def test_rerank_scores_survives_reranker_exception(monkeypatch):
    class Boom:
        def rank(self, **kw):
            raise RuntimeError("model fault")
    monkeypatch.setattr(pipeline, "_get_reranker", lambda: Boom())
    # A reranker fault must degrade to rules, never raise.
    assert pipeline.rerank_scores("q", [{"url": "https://x.com", "title": "t", "snippet": "s"}]) == {}


def test_apply_blocked_hard_vs_soft_increment(tmp_path):
    from src.sessions.worker import _apply_blocked
    from src.state import OpenQuestion, QuestionList

    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([
        OpenQuestion(id="q-001", question="seed", priority=4, created_by="initializer"),
    ]))
    target = run.load_questions().get("q-001")

    class _Out:
        blocked_reason = "no useful reads"

    # soft block: +1
    _apply_blocked(run, target, _Out(), hard_block=False)
    assert run.load_questions().get("q-001").blocked_count == 1
    # hard block: +2 -> now at 3, past the exhausted-scope threshold of 2
    _apply_blocked(run, target, _Out(), hard_block=True)
    assert run.load_questions().get("q-001").blocked_count == 3
    run.release_lock()


# --- compose role routing (COMPREHENSIVE_RESEARCH_SPEC §1) -----------------------------


def _role_capturing_fakes(roles_used: dict[str, str]):
    """fake_session records which role each single-shot call was routed to;
    fake_read returns one useful page so compose actually runs."""

    async def fake_session(**kwargs):
        if kwargs["output_model"] is pipeline.QueryGenOutput:
            roles_used["query-gen"] = kwargs["role"]
            return FakeSpawn(pipeline.QueryGenOutput(queries=["q"], notes="n"))
        roles_used["compose"] = kwargs["role"]
        menu_id = kwargs["user_prompt"].split("[", 1)[1].split("]", 1)[0]
        return FakeSpawn(None, result_text=(
            '{"outcome": "resolved", "confidence": 0.8, "child_questions": [],'
            ' "blocked_reason": "", "progress_note": "composed"}\n'
            f"---FINDING---\nA composed claim. [{menu_id}]"
        ))

    async def fake_read(*, url, **kwargs):
        return _ro("Real Title"), FakeSpawn(None)

    return fake_session, fake_read


def test_compose_routes_to_compose_role_when_configured(tmp_path, monkeypatch):
    # Spec §1 (COMPREHENSIVE_RESEARCH_SPEC): an optional `compose` role routes
    # ONLY the one-shot compose; query-gen stays on the worker role.
    settings = _settings(tmp_path, **{"roles.compose": {
        "endpoint": "anthropic", "model": "claude-haiku-4-5-20251001",
        "max_turns": 4, "max_wall_seconds": 600,
    }})
    run = Runspace.create(tmp_path / "runs", "overall q", "general")
    run.write_text("PLAN.md", "# plan\n")
    target = OpenQuestion(id="q-001", question="assigned?", priority=5,
                          created_by="initializer", status="in_progress")
    run.save_questions(QuestionList([target]))
    roles_used: dict[str, str] = {}
    fake_session, fake_read = _role_capturing_fakes(roles_used)
    monkeypatch.setattr(pipeline, "run_role_session_async", fake_session)
    monkeypatch.setattr(pipeline.reader, "read_source", fake_read)

    result = pipeline.run_pipeline(
        run, settings, 1, Ledger(run), target, FakeProfile([_r("https://a.com/1")])
    )

    assert roles_used == {"query-gen": "worker", "compose": "compose"}
    assert "resolved q-001" in result.summary
    run.release_lock()


def test_compose_falls_back_to_worker_role_when_unconfigured(run_env, monkeypatch):
    # Guarded fallback: BASE_CONFIG has no `compose` role, so behavior must be
    # byte-identical to the certified posture (compose on the worker role).
    run, settings, target = run_env
    roles_used: dict[str, str] = {}
    fake_session, fake_read = _role_capturing_fakes(roles_used)
    monkeypatch.setattr(pipeline, "run_role_session_async", fake_session)
    monkeypatch.setattr(pipeline.reader, "read_source", fake_read)

    pipeline.run_pipeline(
        run, settings, 1, Ledger(run), target, FakeProfile([_r("https://a.com/1")])
    )

    assert roles_used == {"query-gen": "worker", "compose": "worker"}
