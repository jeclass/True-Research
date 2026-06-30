"""Phase 4: profile registry, search fallback selection, academic/searxng
parsers (canned wire fixtures), capture+vision flow — all zero-LLM."""

import asyncio
from pathlib import Path

import pytest
import yaml

from src.errors import ConfigError
from src.ledger import Ledger
from src.profiles import WorkerToolContext, get_profile
from src.profiles.base import search_tools
from src.runspace import Runspace
from src.sessions.base import ReaderError
from src.settings import Settings
from src.state import OpenQuestion
from src.tools import ConnectorError
from src.tools.academic import (
    format_papers,
    parse_arxiv_atom,
    parse_openalex_works,
    parse_pubmed_esearch,
    parse_pubmed_esummary,
    reconstruct_openalex_abstract,
)
from src.tools.search import format_results, parse_searxng_results, parse_serper_results
from tests.conftest import BASE_CONFIG


def _settings(tmp_path: Path, **overrides) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw.setdefault("secrets", {})
    for dotted, value in overrides.items():
        node = raw
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return Settings.model_validate(raw)


# --- registry -------------------------------------------------------------------


def test_profile_registry_resolves_all_configured_profiles():
    for name in BASE_CONFIG["profiles"]:
        profile = get_profile(name)
        assert profile.name == name
        assert profile.rubric().strip() and profile.worker_guidance().strip()


def test_unknown_profile_is_a_config_error():
    with pytest.raises(ConfigError, match="no implementation"):
        get_profile("astrology")


# --- search fallback selection (§1 local-mode constraint) -------------------------


def test_first_party_worker_gets_websearch(tmp_path):
    toolset = search_tools(_settings(tmp_path))
    assert toolset.builtin == ["WebSearch"] and not toolset.mcp_servers


def test_local_worker_without_fallback_is_a_config_error(tmp_path):
    settings = _settings(tmp_path, **{"roles.worker.endpoint": "local"})
    with pytest.raises(ConfigError, match="searxng_base_url"):
        search_tools(settings)


def test_local_worker_with_searxng_gets_mcp_search(tmp_path):
    settings = _settings(
        tmp_path,
        **{
            "roles.worker.endpoint": "local",
            "search.searxng_base_url": "http://localhost:8888",
        },
    )
    toolset = search_tools(settings)
    assert "WebSearch" not in toolset.builtin
    assert "search" in toolset.mcp_servers
    assert toolset.extra_allowed == ["mcp__search__web_search"]


# --- prompt composition ------------------------------------------------------------


def test_worker_prompt_carries_profile_guidance():
    from src.sessions.worker import build_system_prompt

    text = build_system_prompt(get_profile("scientific"))
    assert "search_pubmed" in text and "Domain guidance (profile: scientific)" in text


def test_evaluator_prompt_carries_profile_rubric():
    from src.sessions.evaluator import build_system_prompt

    general = build_system_prompt(get_profile("general"))
    visual = build_system_prompt(get_profile("visual"))
    assert "START FROM FAIL" in general
    assert "Source diversity" in general
    assert "kind=page_capture" in visual and "Coverage" in visual


# --- academic parsers (canned wire fixtures) -----------------------------------------


def test_pubmed_parsers():
    ids = parse_pubmed_esearch(
        {"esearchresult": {"idlist": ["111", "222"], "count": "2"}}
    )
    assert ids == ["111", "222"]
    papers = parse_pubmed_esummary(
        {
            "result": {
                "uids": ["111"],
                "111": {
                    "title": "Melatonin RCT",
                    "fulljournalname": "Sleep Medicine",
                    "pubdate": "2024 Mar",
                    "authors": [{"name": "Doe J"}],
                    "pubtype": ["Randomized Controlled Trial"],
                },
            }
        }
    )
    assert papers[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/"
    assert papers[0]["year"] == "2024"
    text = format_papers(papers, "PubMed")
    assert "Melatonin RCT" in text and "type=Randomized Controlled Trial" in text


def test_pubmed_parser_rejects_garbage():
    with pytest.raises(ConnectorError, match="esearch"):
        parse_pubmed_esearch({"wat": 1})


def test_openalex_parser_reconstructs_abstract():
    assert (
        reconstruct_openalex_abstract({"sleep": [1], "Melatonin": [0], "improves": [2]})
        == "Melatonin sleep improves"
    )
    papers = parse_openalex_works(
        {
            "results": [
                {
                    "title": "A meta-analysis",
                    "publication_year": 2023,
                    "cited_by_count": 41,
                    "primary_location": {
                        "landing_page_url": "https://doi.org/10/xyz",
                        "source": {"display_name": "JAMA"},
                    },
                    "authorships": [{"author": {"display_name": "Roe R"}}],
                    "abstract_inverted_index": {"Hello": [0], "world": [1]},
                }
            ]
        }
    )
    assert papers[0]["venue"] == "JAMA" and papers[0]["abstract"] == "Hello world"
    assert "cited_by=41" in format_papers(papers, "OpenAlex")


def test_arxiv_atom_parser():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2401.00001</id>
        <title>Sleep  and\n   transformers</title>
        <summary>We study   sleep.</summary>
        <published>2024-01-01T00:00:00Z</published>
        <author><name>A. Author</name></author>
      </entry>
    </feed>"""
    papers = parse_arxiv_atom(xml)
    assert papers[0]["title"] == "Sleep and transformers"
    assert papers[0]["year"] == "2024"
    assert papers[0]["url"] == "http://arxiv.org/abs/2401.00001"
    with pytest.raises(ConnectorError):
        parse_arxiv_atom("<not-xml")


# --- searxng parser --------------------------------------------------------------------


def test_searxng_parser_and_format():
    results = parse_searxng_results(
        {"results": [{"title": "T", "url": "https://x.org", "content": "snippet"}] * 3},
        max_results=2,
    )
    assert len(results) == 2
    assert "https://x.org" in format_results(results)


# --- serper (Google SERP) parser + provider selection ----------------------------------


def test_serper_parser_takes_organic_skips_linkless():
    # Serper returns Google's SERP; we keep the `organic` block as (title,url,snippet).
    # A result with no link is unreadable -> dropped (can't feed the reader a non-URL).
    results = parse_serper_results(
        {"organic": [
            {"title": "A", "link": "https://a.org", "snippet": "s1"},
            {"title": "B", "snippet": "no link here"},
            {"title": "C", "link": "https://c.org", "snippet": "s3"},
        ]},
        max_results=10,
    )
    assert [r["url"] for r in results] == ["https://a.org", "https://c.org"]
    assert results[0]["snippet"] == "s1"


def test_serper_parser_rejects_garbage():
    from src.tools import ConnectorError

    with pytest.raises(ConnectorError):
        parse_serper_results({"organic": "not-a-list"}, max_results=5)


def test_decode_json_wraps_non_jsondecode_failures():
    # audit #3: response.json() can raise UnicodeDecodeError / LookupError /
    # AssertionError from a bogus Content-Encoding/charset — NONE of which subclass
    # httpx.HTTPError or json.JSONDecodeError, so the old narrow
    # `except (httpx.HTTPError, json.JSONDecodeError)` let them escape search.py
    # and crash a worker session (the bug fixed in reader.py 72c5546 and ported to
    # academic.py 9192bd1). The shared guard must convert ANY decode failure into a
    # clean ConnectorError so the run degrades (fall to next provider) not crashes.
    from src.tools import ConnectorError
    from src.tools.search import _decode_json

    class _Resp:
        def __init__(self, exc):
            self._exc = exc

        def json(self):
            raise self._exc

    for exc in (
        LookupError("unknown encoding: base64"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        AssertionError("httpx decoder invariant"),
    ):
        with pytest.raises(ConnectorError, match="undecodable body"):
            _decode_json(_Resp(exc), "TestProvider")


def test_general_profile_prefers_serper_when_key_present(tmp_path):
    # Portability contract: with SERPER_API_KEY in .env the web slot is Serper
    # (Google) + OpenAlex; without it, the engine falls back to the SearXNG->DDG
    # base provider so a fresh clone still searches with no key and no Docker.
    from src.profiles.general import GeneralProfile

    with_key = _settings(
        tmp_path,
        **{"search.serper_api_key_env": "SERPER_API_KEY"},
        secrets={"ANTHROPIC_API_KEY": "sk", "SERPER_API_KEY": "k"},
    )
    assert [n for n, _ in GeneralProfile().pipeline_search_providers(with_key)] == [
        "openalex", "serper",
    ]

    no_key = _settings(tmp_path, **{"search.serper_api_key_env": "SERPER_API_KEY"})
    assert [n for n, _ in GeneralProfile().pipeline_search_providers(no_key)] == [
        "openalex", "search",
    ]


# --- PDF report output -----------------------------------------------------------------


def test_render_markdown_pdf_writes_valid_pdf(tmp_path):
    from src.tools.report_pdf import render_markdown_pdf

    md = "# Title\n\n**Bold** and a [link](https://x.org).\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    pdf = tmp_path / "REPORT.pdf"
    ok, detail = render_markdown_pdf(md, pdf)
    assert ok, detail
    assert pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-"


def test_render_markdown_pdf_never_raises(tmp_path):
    # PDF must never crash a finished run — an unwritable target degrades to
    # (False, reason), not an exception (the markdown is the source of truth).
    from src.tools.report_pdf import render_markdown_pdf

    ok, detail = render_markdown_pdf("# x", tmp_path / "missing-dir" / "REPORT.pdf")
    assert ok is False and detail


# --- evaluator: comprehensive widens stopping discipline to keep context ----------------


def test_evaluator_comprehensive_note_widens_stopping_discipline():
    # Detail-inclusion fix: in comprehensive mode the evaluator keeps directly-
    # relevant context (e.g. how a recommendation compares to the standard options)
    # instead of closing it 'immaterial'. Normal runs stay tight (note absent).
    from src.profiles import get_profile
    from src.sessions.evaluator import build_system_prompt

    p = get_profile("general")
    normal = build_system_prompt(p, comprehensive=False)
    comp = build_system_prompt(p, comprehensive=True)
    assert "COMPREHENSIVE run" in comp and "COMPREHENSIVE run" not in normal
    # Still the default-FAIL gate in both modes — we widened scope, not rigor.
    assert "START FROM FAIL" in normal and "START FROM FAIL" in comp


# --- capture + vision flow ----------------------------------------------------------------


@pytest.fixture
def ctx(tmp_path):
    settings = _settings(tmp_path)
    run = Runspace.create(tmp_path / "runs", "visual q", "visual")
    target = OpenQuestion(id="q-001", question="hero layouts?", priority=5,
                          created_by="initializer")
    yield WorkerToolContext(
        run=run, settings=settings, ledger=Ledger(run), cycle=1,
        target=target, stats={"reads": 0, "failures": 0}, read_urls=set(),
    )
    run.release_lock()


def test_capture_failure_counts_and_reports(ctx, monkeypatch):
    from src.profiles import visual as visual_mod

    async def boom(url, run, settings):
        raise ConnectorError("page capture failed for test: no browser")

    monkeypatch.setattr(visual_mod, "capture_page", boom)
    result = asyncio.run(visual_mod.handle_capture(ctx, {"url": "https://a.com", "why": "w"}))
    assert result["is_error"] and "CAPTURE FAILED" in result["content"][0]["text"]
    assert ctx.stats["failures"] == 1 and not ctx.read_urls


def test_capture_success_registers_read_and_returns_analysis(ctx, monkeypatch):
    from src.profiles import visual as visual_mod
    from src.sessions.reader import ReaderOutput

    async def fake_capture(url, run, settings):
        return "captures/001-a-com.png"

    async def fake_analyze(**kwargs):
        return (
            ReaderOutput(
                useful=True, title="Acme hero", kind="page_capture",
                credibility=80, notes="landing page",
                summary_markdown="3 badges under CTA; 70% lifestyle imagery",
            ),
            None,
        )

    monkeypatch.setattr(visual_mod, "capture_page", fake_capture)
    monkeypatch.setattr(visual_mod, "analyze_capture", fake_analyze)
    result = asyncio.run(visual_mod.handle_capture(ctx, {"url": "https://a.com/", "why": "w"}))
    text = result["content"][0]["text"]
    assert "VISUAL ANALYSIS" in text and "3 badges" in text
    assert "https://a.com" in ctx.read_urls  # capture satisfies the read-gate
    assert ctx.stats["reads"] == 1


def test_capture_page_missing_playwright_is_typed(ctx, monkeypatch):
    import sys

    from src.tools import capture as capture_mod

    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    with pytest.raises(ConnectorError, match="pip install playwright"):
        asyncio.run(capture_mod.capture_page("https://a.com", ctx.run, ctx.settings))


def test_analyze_capture_validates_credibility(ctx, monkeypatch):
    from src.sessions.reader import ReaderOutput
    from src.tools import capture as capture_mod

    class FakeSpawn:
        structured = ReaderOutput(
            useful=True, title="t", kind="page_capture", credibility=999,
            notes="", summary_markdown="s",
        )

    async def fake_session(**kwargs):
        return FakeSpawn()

    monkeypatch.setattr(capture_mod, "run_role_session_async", fake_session)
    with pytest.raises(ReaderError, match="999"):
        asyncio.run(
            capture_mod.analyze_capture(
                run=ctx.run, settings=ctx.settings, ledger=ctx.ledger, cycle=1,
                relpath="captures/x.png", url="https://a.com", question="q", why="w",
            )
        )
