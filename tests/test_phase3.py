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


def test_finalize_metrics_zeroes_usd_on_local_endpoints():
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 10,
        "cache_creation_input_tokens": 5,
    }
    local = finalize_metrics(usage, 1.23, endpoint_is_local=True, wall_seconds=2.0)
    cloud = finalize_metrics(usage, 1.23, endpoint_is_local=False, wall_seconds=2.0)
    assert local["usd"] == 0.0 and cloud["usd"] == 1.23
    assert local["input_tokens"] == 100 and local["cached_tokens"] == 15


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


def test_evaluator_close_of_resolved_question_is_an_error(run):
    _seed_questions(run)
    with pytest.raises(EvalError, match="already resolved"):
        evaluator._apply_output(
            run, _eval_output(close_questions=[{"id": "q-001", "reason": "r"}]), 1
        )


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
