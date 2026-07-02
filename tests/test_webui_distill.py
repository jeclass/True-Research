"""Distill route — one-shot pre-launch intent preview. Hermetic: the SDK
seam (_query_structured) is monkeypatched; no network, no key use."""

import pytest

from src.webui import distill_api


def _client(tmp_path, env_lines=""):
    from starlette.testclient import TestClient
    from src.webui.app import create_app
    env = tmp_path / ".env"
    if env_lines:
        env.write_text(env_lines, encoding="utf-8")
    return TestClient(create_app(runs_dir=tmp_path / "runs", env_path=env))


def test_distill_returns_structured_preview(tmp_path, monkeypatch):
    async def fake_query(text, api_key):
        assert api_key == "sk-ant-x"
        assert "pasted wall of text" in text
        return distill_api.DistillOutput(
            research_question="Does X cause Y in adults?",
            context_summary="User is deciding whether to take X.",
        )
    monkeypatch.setattr(distill_api, "_query_structured", fake_query)
    c = _client(tmp_path, "ANTHROPIC_API_KEY=sk-ant-x\n")
    r = c.post("/api/distill", json={"text": "pasted wall of text " * 30})
    assert r.status_code == 200
    body = r.json()
    assert body["research_question"] == "Does X cause Y in adults?"
    assert body["context_summary"].startswith("User is deciding")


def test_distill_409_without_anthropic_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = _client(tmp_path)
    r = c.post("/api/distill", json={"text": "some long brief"})
    assert r.status_code == 409


def test_distill_502_on_session_failure_no_text_echo(tmp_path, monkeypatch):
    async def boom(text, api_key):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(distill_api, "_query_structured", boom)
    c = _client(tmp_path, "ANTHROPIC_API_KEY=sk-ant-x\n")
    r = c.post("/api/distill", json={"text": "SECRET-BRIEF-CONTENT"})
    assert r.status_code == 502
    assert "SECRET-BRIEF-CONTENT" not in r.text
    assert "model exploded" not in r.text  # generic detail only


def test_distill_rejects_blank_and_oversize(tmp_path):
    c = _client(tmp_path, "ANTHROPIC_API_KEY=sk-ant-x\n")
    assert c.post("/api/distill", json={"text": "   "}).status_code == 422
    r = c.post("/api/distill", json={"text": "y" * 300_000})
    assert r.status_code == 422
    assert "y" * 1000 not in r.text  # oversize paste not echoed back


def test_distill_env_file_wins_over_environ(tmp_path, monkeypatch):
    async def fake_query(text, api_key):
        assert api_key == "sk-from-envfile"
        return distill_api.DistillOutput(research_question="q", context_summary="c")
    monkeypatch.setattr(distill_api, "_query_structured", fake_query)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-environ")
    c = _client(tmp_path, "ANTHROPIC_API_KEY=sk-from-envfile\n")
    assert c.post("/api/distill", json={"text": "brief"}).status_code == 200
