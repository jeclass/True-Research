"""Phase 3: reader fan-out plumbing, prompted-JSON path, local-endpoint
attribution, evaluator adjudication/close machinery."""

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from src.errors import StateError
from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import evaluator
from src.sessions.base import (
    EvalError,
    ReaderError,
    finalize_metrics,
    json_response_instructions,
    parse_prompted_json,
)
from src.sessions.reader import ReaderOutput, extract_text, fetch_page
from src.settings import Settings
from src.state import LedgerEntry, OpenQuestion, QuestionList
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


# --- prompted JSON (the local-endpoint structured path) -----------------------


_READER_JSON = json.dumps(
    {
        "useful": True,
        "title": "Mock Trial Report",
        "kind": "paper",
        "credibility": 85,
        "notes": "RCT, 2024",
        "summary_markdown": "ADF lost 0.7 kg more (p=0.31) [not significant].",
    }
)


def test_parse_prompted_json_plain_fenced_and_prose():
    for text in (
        _READER_JSON,
        f"```json\n{_READER_JSON}\n```",
        f"Here is the JSON you asked for:\n{_READER_JSON}\nHope that helps!",
    ):
        out = parse_prompted_json(text, ReaderOutput)
        assert out.credibility == 85 and out.useful is True


def test_parse_prompted_json_garbage_fails_loudly():
    with pytest.raises(ValueError, match="prompted-JSON parse failed"):
        parse_prompted_json("I could not produce JSON, sorry.", ReaderOutput)


def test_json_response_instructions_embed_schema():
    text = json_response_instructions(ReaderOutput)
    assert "single JSON object" in text and '"credibility"' in text


# --- metrics / ledger attribution ---------------------------------------------


def test_finalize_metrics_cost_precedence():
    from src.settings import EndpointCfg

    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 10,
        "cache_creation_input_tokens": 5,
    }
    first_party = EndpointCfg(base_url=None, auth_env="ANTHROPIC_API_KEY")
    free_local = EndpointCfg(base_url="http://localhost:11434", auth_env="OLLAMA_AUTH")
    paid_third_party = EndpointCfg(
        base_url="https://api.example.com",
        auth_env="SOME_KEY",
        price_per_mtok={"input": 1.0, "output": 5.0},
    )
    cloud = finalize_metrics(usage, 1.23, first_party, wall_seconds=2.0)
    local = finalize_metrics(usage, 1.23, free_local, wall_seconds=2.0)
    paid = finalize_metrics(usage, None, paid_third_party, wall_seconds=2.0)
    assert cloud["usd"] == 1.23          # CLI estimate on first-party
    assert local["usd"] == 0.0           # free local => §1 usd 0
    # paid third-party: (100+15 cached)*$1/M + 50*$5/M
    assert paid["usd"] == pytest.approx((115 * 1.0 + 50 * 5.0) / 1_000_000)
    assert local["input_tokens"] == 100 and local["cached_tokens"] == 15


def test_http_get_with_retry_recovers_from_transient_5xx(tmp_path):
    """Flaky server: two 503s then 200 — the retrying GET must succeed.
    A permanent 403 must NOT be retried."""
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpx

    from src.tools import http_get_with_retry

    state = {"calls": 0, "fail_first": 2, "status": 503}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["calls"] += 1
            if state["calls"] <= state["fail_first"]:
                self.send_response(state["status"])
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    url = f"http://{host}:{port}/x"
    retry_cfg = _settings(tmp_path).retry  # conftest: 3 attempts, ms delays

    try:
        response = asyncio.run(
            http_get_with_retry(url, retry_cfg=retry_cfg, timeout=5)
        )
        assert response.status_code == 200 and state["calls"] == 3

        # permanent failure: 403 raises immediately, exactly one call
        state.update(calls=0, fail_first=99, status=403)
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(http_get_with_retry(url, retry_cfg=retry_cfg, timeout=5))
        assert state["calls"] == 1

        # exhaustion: all attempts 503 -> TransportError naming the attempts
        state.update(calls=0, fail_first=99, status=503)
        with pytest.raises(httpx.TransportError, match="after 3 attempts"):
            asyncio.run(http_get_with_retry(url, retry_cfg=retry_cfg, timeout=5))
        assert state["calls"] == 3
    finally:
        server.shutdown()
        server.server_close()


def test_is_transient_result_classification():
    from src.sessions.base import is_transient_result

    assert is_transient_result(True, "success", 529)
    assert is_transient_result(True, "error_during_execution", 503)
    assert not is_transient_result(True, "error_during_execution", None)
    assert not is_transient_result(True, "error_max_budget_usd", 400)
    assert not is_transient_result(False, "success", None)


def test_reader_session_type_is_a_valid_ledger_entry():
    entry = LedgerEntry(
        cycle=1,
        session_type="reader",
        model="qwen3:4b-instruct-2507-q4_K_M",
        endpoint="local",
        input_tokens=10,
        output_tokens=5,
        cached_tokens=0,
        usd=0.0,
        wall_seconds=1.0,
    )
    assert entry.session_type == "reader" and entry.usd == 0.0


def test_is_full_local_detection(tmp_path):
    assert _settings(tmp_path).is_full_local() is False
    overrides = {
        f"roles.{role}.endpoint": "local"
        for role in BASE_CONFIG["roles"]
    }
    assert _settings(tmp_path, **overrides).is_full_local() is True


# --- page fetch / extraction ----------------------------------------------------


def test_extract_text_strips_script_style_nav():
    html = (
        "<html><head><title>t</title><style>x{}</style></head><body>"
        "<nav>menu junk</nav><script>var x=1;</script>"
        "<h1>Real Title</h1><p>Real content here.</p></body></html>"
    )
    text = extract_text(html)
    assert "Real content here." in text and "Real Title" in text
    assert "var x=1" not in text and "menu junk" not in text


def test_fetch_page_failure_is_a_reader_error(tmp_path):
    settings = _settings(tmp_path, **{"reader.fetch_timeout_seconds": 2})
    with pytest.raises(ReaderError, match="fetch failed"):
        asyncio.run(fetch_page("http://127.0.0.1:9/none", settings))


def test_fetch_via_httpx_undecodable_body_is_reader_error(tmp_path, monkeypatch):
    # Robustness (2026-06-24): a server declaring a bogus Content-Encoding (e.g.
    # `base64`) makes httpx's response.text raise AssertionError — a NON-HTTPError
    # that the fetch guard missed, so it crashed a live multi-cycle run. It must
    # surface as a failed read instead.
    import src.tools as tools_mod
    from src.sessions import reader as reader_mod

    class _Undecodable:
        headers = {"content-type": "text/html"}

        @property
        def text(self):
            raise AssertionError("base64 codec strict-mode")

    async def _fake_get(url, **kwargs):
        return _Undecodable()

    monkeypatch.setattr(tools_mod, "http_get_with_retry", _fake_get)
    settings = _settings(tmp_path)
    with pytest.raises(ReaderError, match="undecodable"):
        asyncio.run(reader_mod._fetch_via_httpx("https://bad.example/x", settings))


def test_normalize_url_forgives_slash_case_fragment():
    from src.sessions.common import normalize_url

    base = normalize_url("https://Example.ORG/Path/")
    assert normalize_url("https://example.org/Path") == base
    assert normalize_url("https://example.org/Path/#section") == base
    # path case is preserved (paths can be case-sensitive); host/scheme lowered
    assert normalize_url("https://example.org/OTHER") != base


# --- evaluator adjudication / close machinery ------------------------------------


@pytest.fixture
def run(tmp_path: Path):
    r = Runspace.create(tmp_path / "runs", "q", "general")
    yield r
    r.release_lock()


def _eval_output(**kw) -> evaluator.EvaluatorOutput:
    base = dict(
        passed=False,
        unmet_criteria=["x"],
        contradictions=[],
        new_questions=[],
        close_questions=[],
        notes="n",
    )
    base.update(kw)
    return evaluator.EvaluatorOutput.model_validate(base)


def _seed_questions(run: Runspace) -> None:
    run.save_questions(
        QuestionList(
            [
                OpenQuestion(id="q-001", question="core", priority=5,
                             created_by="initializer", status="resolved",
                             resolved_by_finding="q-001-c01"),
                OpenQuestion(id="q-002", question="marginal", priority=2,
                             created_by="evaluator", status="open"),
            ]
        )
    )


def test_evaluator_close_marks_resolved_and_logs_decision(run):
    _seed_questions(run)
    output = _eval_output(
        passed=True,
        unmet_criteria=[],
        close_questions=[{"id": "q-002", "reason": "immaterial to conclusion"}],
    )
    passed, _notes, added, closed = evaluator._apply_output(run, output, cycle=3)
    assert passed is True and closed == ["q-002"] and added == []
    assert run.load_questions().get("q-002").status == "resolved"
    assert any("closed q-002 as immaterial" in d for d in run.decisions())


def test_evaluator_reclose_of_resolved_question_is_idempotent(run):
    # Evaluators re-judge the whole questions file each cycle and may
    # redundantly re-close a settled question (observed smoke5 2026-06-10).
    # Harmless staleness is a logged no-op; only unknown ids stay fatal.
    run.save_questions(QuestionList([
        OpenQuestion(id="q-010", question="explored", priority=2,
                     created_by="evaluator", status="resolved",
                     resolved_by_finding="q-010-c01"),
        OpenQuestion(id="q-011", question="still open", priority=3,
                     created_by="evaluator", status="open"),
    ]))
    passed, _notes, _added, closed = evaluator._apply_output(
        run, _eval_output(close_questions=[{"id": "q-010", "reason": "r"}]), 1
    )
    assert closed == []
    assert run.load_questions().get("q-010").status == "resolved"


def test_evaluator_cannot_close_seed_questions(run):
    # Observed smoke7 2026-06-10: the local evaluator closed a mandated-scope
    # facet as "immaterial" and the judge scored completeness 5/10. Seed
    # (initializer-created) questions are the run's contract — closes are
    # refused loudly and the question stays open.
    run.save_questions(QuestionList([
        OpenQuestion(id="q-020", question="mandated facet", priority=4,
                     created_by="initializer", status="open"),
    ]))
    passed, _notes, _added, closed = evaluator._apply_output(
        run, _eval_output(close_questions=[{"id": "q-020", "reason": "immaterial"}]), 2
    )
    assert closed == []
    assert run.load_questions().get("q-020").status == "open"
    assert any("REFUSED" in d and "q-020" in d for d in run.decisions())


def test_evaluator_close_of_unknown_question_is_an_error(run):
    _seed_questions(run)
    with pytest.raises(StateError, match="unknown question id"):
        evaluator._apply_output(
            run, _eval_output(close_questions=[{"id": "q-099", "reason": "r"}]), 1
        )


def test_evaluator_pass_with_open_questions_is_overridden(run):
    _seed_questions(run)
    passed, notes, _added, _closed = evaluator._apply_output(
        run, _eval_output(passed=True, unmet_criteria=[]), cycle=2
    )
    assert passed is False and "pass overridden" in notes


def test_evaluator_new_questions_are_appended_with_ids(run):
    _seed_questions(run)
    output = _eval_output(
        new_questions=[{"question": "deeper", "priority": 4, "parent_id": "q-001"}]
    )
    _passed, _notes, added, _closed = evaluator._apply_output(run, output, cycle=2)
    assert added == ["q-003"]
    q = run.load_questions().get("q-003")
    assert q.created_by == "evaluator" and q.parent_id == "q-001"


# --- end-to-end against the mock local endpoint -----------------------------------


def test_local_endpoint_e2e_via_mock_server(tmp_path, monkeypatch):
    """The strongest in-container verification of the hybrid path: a REAL CLI
    subprocess, pointed at a mock /v1/messages server via per-session env
    injection, authenticated with the local bearer token, parsed via the
    prompted-JSON path, and ledgered as endpoint=local with usd=0."""
    from src.sessions import base as base_mod
    from tests.anthropic_mock import MockAnthropicServer

    with MockAnthropicServer(reply_text=_READER_JSON) as mock:
        settings = _settings(
            tmp_path,
            **{
                "session.backend": "sdk",
                "endpoints.local.base_url": mock.base_url,
                "roles.reader_subagent.endpoint": "local",
                "roles.reader_subagent.model": "mock-local-model",
            },
        )
        object.__setattr__  # noqa: B018 — settings is frozen; secrets injected below
        settings = Settings.model_validate(
            {**settings.model_dump(), "secrets": {"OLLAMA_AUTH": "ollama"}}
        )

        real_resolve = base_mod.resolve_endpoint_env

        def resolve_with_test_speedups(settings_, role_name):
            env = real_resolve(settings_, role_name)
            env.update(
                {
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "CLAUDE_CODE_MAX_RETRIES": "1",
                    "API_TIMEOUT_MS": "30000",
                }
            )
            return env

        monkeypatch.setattr(base_mod, "resolve_endpoint_env", resolve_with_test_speedups)

        run = Runspace.create(tmp_path / "runs", "mock e2e", "general")
        try:
            ledger = Ledger(run)
            spawn = base_mod.run_role_session(
                run=run,
                settings=settings,
                ledger=ledger,
                cycle=1,
                session_type="reader",
                role="reader_subagent",
                system_prompt="You summarize one page. No tools.",
                user_prompt="Summarize: ADF lost 0.7 kg more (p=0.31).",
                tools=[],
                output_model=ReaderOutput,
            )
        finally:
            run.release_lock()

    out: ReaderOutput = spawn.structured
    assert out.useful is True and out.credibility == 85

    # Ledger: attributed to the local endpoint at usd=0, tokens recorded.
    entries = [e for e in ledger.entries if e.session_type == "reader"]
    assert entries and entries[-1].endpoint == "local"
    assert entries[-1].usd == 0.0
    assert entries[-1].input_tokens > 0

    # Wire: the CLI hit the mock at the injected base_url with the routed model.
    hits = [r for r in mock.recorded.requests if r["path"].startswith("/v1/messages")]
    assert hits, "mock server never received a /v1/messages call"
    primary = [r for r in hits if r["model"] == "mock-local-model"]
    assert primary, f"expected mock-local-model in requests, got {[r['model'] for r in hits]}"

    # Auth assertion is machine-conditional. Verified empirically (see
    # docs/SDK_NOTES.md): host-broker environments (Claude Code on the web,
    # CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST set) pin spawned-session auth to
    # the broker and ignore injected ANTHROPIC_AUTH_TOKEN/API_KEY entirely.
    # On standard machines the injected bearer must win — asserted here;
    # scripts/check_local_backend.py performs the same check against a real
    # local endpoint.
    import os

    if "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST" not in os.environ:
        assert any(r["authorization"] == "Bearer ollama" for r in primary)
        assert all(not r["x_api_key"] for r in hits)
    # else: broker-managed environment — auth is host-pinned by design and
    # unassertable here; the routing/ledger assertions above still hold.


def test_evaluator_retries_parse_failures(run, tmp_path, monkeypatch):
    # Observed smoke11 2026-06-10: local evaluator emitted unterminated JSON
    # and killed the run - evaluator sessions reroll like pipeline one-shots.
    _seed_questions(run)
    run.write_text("PLAN.md", "# plan\n")
    settings = _settings(tmp_path)
    calls = {"n": 0}

    class _Spawn:
        def __init__(self, structured):
            self.structured = structured
            self.input_tokens = 1
            self.output_tokens = 1
            self.cached_tokens = 0
            self.usd = 0.0
            self.wall_seconds = 0.1
            self.num_turns = 1

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise EvalError("evaluator session did not return parseable JSON - x")
        return _Spawn(_eval_output(passed=False))

    monkeypatch.setattr(evaluator, "run_role_session", flaky)
    result = evaluator.run(run, settings, 1, Ledger(run))
    assert calls["n"] == 3
    assert result.session_type == "evaluator"


def test_synthesizer_degrades_hallucinated_citations_instead_of_crashing(tmp_path, monkeypatch):
    # Observed live 2026-06-24: DeepSeek Pro synth cited non-existent ids like
    # `src-q-003-finding`; the citation pass raised and crashed a COMPLETED run at
    # the final step. Now it retries with feedback, then neutralizes any still-bad
    # citation to [citation-unresolved] so a finished run always yields a report.
    from src.sessions import synthesizer
    from src.sessions.synthesizer import SynthesizerOutput, _synthesize_factual
    from src.state import SourceRecord, SourceRegistry, utcnow

    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_text("PLAN.md", "# plan\n")
    settings = _settings(tmp_path)
    sources = SourceRegistry(root={
        "src-real": SourceRecord(url="https://e/1", title="t", kind="web",
                                 credibility=80, retrieved_at=utcnow(), notes=""),
    })

    class _Spawn:
        def __init__(self, md):
            self.structured = SynthesizerOutput(report_markdown=md)
            self.input_tokens = self.output_tokens = self.cached_tokens = 1
            self.usd = 0.0
            self.wall_seconds = 0.1
            self.num_turns = 1

    # Always cites a non-existent id -> after retries it must be neutralized.
    monkeypatch.setattr(
        synthesizer, "run_role_session",
        lambda **kw: _Spawn("Claim one [src-real]. Claim two [src-q-003-finding]."),
    )
    body, _ = _synthesize_factual(run, settings, Ledger(run), 1, sources)
    assert "[citation-unresolved]" in body         # hallucinated id neutralized
    assert "[src-q-003-finding]" not in body        # the bad id is gone
    assert "[src-real]" in body                     # the valid one survives
    assert any("unresolvable" in d for d in run.decisions())
    run.release_lock()


def test_evaluator_seed_close_refused_below_blocked_threshold(run):
    qs = run.load_questions() if (run.root / "open_questions.yaml").exists() else None
    run.save_questions(QuestionList([
        OpenQuestion(id="q-001", question="seed facet", priority=4,
                     created_by="initializer", status="open", blocked_count=1),
    ]))
    passed, _n, _a, closed = evaluator._apply_output(
        run, _eval_output(close_questions=[{"id": "q-001", "reason": "thin"}]), 1
    )
    assert closed == []
    assert run.load_questions().get("q-001").status == "open"
    assert any("REFUSED" in d for d in run.decisions())


def test_evaluator_seed_close_allowed_after_two_blocks(run):
    run.save_questions(QuestionList([
        OpenQuestion(id="q-001", question="seed facet", priority=4,
                     created_by="initializer", status="open", blocked_count=2),
    ]))
    passed, _n, _a, closed = evaluator._apply_output(
        run, _eval_output(close_questions=[{"id": "q-001", "reason": "no sources exist"}]), 3
    )
    assert closed == ["q-001"]
    assert run.load_questions().get("q-001").status == "resolved"
    assert any("EXHAUSTED SCOPE" in d for d in run.decisions())


def test_fetch_page_stealth_fallback_rescues_bot_walled_page(tmp_path, monkeypatch):
    # 2026-06-11: ~5-7 of 12 selected reads failed on 403/JS-only pages.
    # Tier-2 stealth converts them into usable reads.
    from src.sessions import reader as reader_mod

    settings = _settings(tmp_path, **{"reader.fetch_timeout_seconds": 2})

    async def httpx_403(url, s):
        raise ReaderError(f"fetch failed for {url}: 403 Forbidden")

    monkeypatch.setattr(reader_mod, "_fetch_via_httpx", httpx_403)
    monkeypatch.setattr(reader_mod, "_stealth_available", lambda: True)
    monkeypatch.setattr(
        reader_mod, "_stealth_fetch_sync",
        lambda url, t: "<html><body><p>rescued content</p></body></html>",
    )
    text = asyncio.run(reader_mod.fetch_page("https://blocked.example/x", settings))
    assert "rescued content" in text


def test_fetch_page_surfaces_original_error_when_stealth_fails(tmp_path, monkeypatch):
    from src.sessions import reader as reader_mod

    settings = _settings(tmp_path, **{"reader.fetch_timeout_seconds": 2})

    async def httpx_403(url, s):
        raise ReaderError("fetch failed for x: 403 Forbidden")

    def stealth_also_blocked(url, t):
        raise ReaderError("stealth fetch for x returned HTTP 403")

    monkeypatch.setattr(reader_mod, "_fetch_via_httpx", httpx_403)
    monkeypatch.setattr(reader_mod, "_stealth_available", lambda: True)
    monkeypatch.setattr(reader_mod, "_stealth_fetch_sync", stealth_also_blocked)
    with pytest.raises(ReaderError, match="403 Forbidden"):
        asyncio.run(reader_mod.fetch_page("https://blocked.example/x", settings))


def test_fetch_page_no_stealth_when_disabled(tmp_path, monkeypatch):
    from src.sessions import reader as reader_mod

    settings = _settings(
        tmp_path,
        **{"reader.fetch_timeout_seconds": 2, "reader.stealth_fallback": False},
    )
    calls = {"stealth": 0}

    async def httpx_403(url, s):
        raise ReaderError("fetch failed: 403")

    def count_stealth(url, t):
        calls["stealth"] += 1
        return "<html>x</html>"

    monkeypatch.setattr(reader_mod, "_fetch_via_httpx", httpx_403)
    monkeypatch.setattr(reader_mod, "_stealth_available", lambda: True)
    monkeypatch.setattr(reader_mod, "_stealth_fetch_sync", count_stealth)
    with pytest.raises(ReaderError):
        asyncio.run(reader_mod.fetch_page("https://x.example/", settings))
    assert calls["stealth"] == 0
