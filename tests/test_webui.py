"""Web UI backend — read-only run-state layer + API routes. Hermetic: builds a
fixture runs/ dir on disk, never spawns a process or hits the network."""

import json
from pathlib import Path

import pytest

from src.webui import runs_api


def _make_run(runs_dir: Path, run_id: str, *, status="running", finished_files=False):
    d = runs_dir / run_id
    (d / "findings").mkdir(parents=True)
    (d / "verdicts").mkdir()
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "question": "Does X cause Y?", "profile": "general",
        "created_at": "2026-07-02T00:00:00+00:00", "status": status,
        "finish_reason": "conclusive" if status == "finished" else None,
        "last_cycle": 2, "stall_count": 0, "active_seconds": 123.0,
        "final_eval_count": 1, "read_outage_streak": 0, "wave": "breadth",
    }), encoding="utf-8")
    (d / "ledger.json").write_text(json.dumps([
        {"cycle": 1, "session_type": "initializer", "model": "claude-opus-4-8",
         "endpoint": "anthropic", "input_tokens": 10, "output_tokens": 20,
         "cached_tokens": 0, "usd": 0.5, "wall_seconds": 3.0, "reconciled": True},
        {"cycle": 1, "session_type": "reader", "model": "deepseek-v4-flash",
         "endpoint": "deepseek_flash", "input_tokens": 5, "output_tokens": 5,
         "cached_tokens": 0, "usd": 0.01, "wall_seconds": 1.0, "reconciled": True},
    ]), encoding="utf-8")
    (d / "PROGRESS.md").write_text(
        "# Progress\n\n- [t] worker: did a thing\n\n## DECISIONS\n- [t] dropped a weak source\n",
        encoding="utf-8")
    (d / "open_questions.yaml").write_text(
        "- id: q-001\n  question: Does X cause Y?\n  status: resolved\n  priority: 5\n"
        "  parent_id: null\n  created_by: initializer\n  resolved_by_finding: q-001-c01\n",
        encoding="utf-8")
    (d / "sources.json").write_text(json.dumps({
        "src-a": {"url": "https://x.org/a", "title": "Study A", "kind": "paper",
                  "credibility": 90, "retrieved_at": "2026-07-02T00:00:00+00:00",
                  "notes": "RCT", "excerpts": ["X raised Y by 12%."]}}), encoding="utf-8")
    (d / "findings" / "q-001-c01.md").write_text(
        "---\nquestion_id: q-001\nsource_ids: [src-a]\nconfidence: 0.9\n"
        "verification_status: verified\n---\nX raises Y. [src-a]\n", encoding="utf-8")
    if finished_files:
        (d / "REPORT.md").write_text("# Report\n\nX raises Y [src-a].\n\n## Source registry\n"
                                     "- `src-a` — Study A (paper, credibility 90): https://x.org/a\n",
                                     encoding="utf-8")
        (d / "REPORT.pdf").write_bytes(b"%PDF-1.4 fake pdf bytes")
    return d


def test_list_runs_newest_first_with_spend(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260101-000000-aaaa")
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    out = runs_api.list_runs(runs)
    assert [r["run_id"] for r in out] == ["20260102-000000-bbbb", "20260101-000000-aaaa"]
    r0 = out[0]
    assert r0["status"] == "finished" and r0["finish_reason"] == "conclusive"
    assert r0["spend_usd"] == pytest.approx(0.51)
    assert r0["question"].startswith("Does X")
    assert r0["has_report"] is True
    assert out[1]["has_report"] is False


def test_list_runs_empty_dir_is_empty_list(tmp_path):
    assert runs_api.list_runs(tmp_path / "nope") == []


def test_get_run_detail_assembles_state(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260101-000000-aaaa")
    d = runs_api.get_run_detail(runs, "20260101-000000-aaaa")
    assert d["meta"]["run_id"] == "20260101-000000-aaaa"
    assert d["spend_usd"] == pytest.approx(0.51)
    assert d["ledger_by_type"]["reader"] == 1 and d["ledger_by_type"]["initializer"] == 1
    q = d["questions"]
    assert q[0]["id"] == "q-001" and q[0]["status"] == "resolved"
    f = d["findings"]
    assert f[0]["slug"] == "q-001-c01" and f[0]["verification_status"] == "verified"
    assert f[0]["question_id"] == "q-001"
    assert "dropped a weak source" in "\n".join(d["decisions"])


def test_get_run_detail_partial_run_no_crash(tmp_path):
    runs = tmp_path / "runs"
    d = runs / "20260101-000000-cccc"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": "20260101-000000-cccc", "question": "Q", "profile": "general",
        "created_at": "2026-07-02T00:00:00+00:00", "status": "running",
        "finish_reason": None, "last_cycle": 0, "stall_count": 0,
        "active_seconds": 1.0, "final_eval_count": 0, "read_outage_streak": 0,
        "wave": "breadth"}), encoding="utf-8")
    detail = runs_api.get_run_detail(runs, "20260101-000000-cccc")
    assert detail["spend_usd"] == 0.0
    assert detail["questions"] == [] and detail["findings"] == [] and detail["sources"] == {}
    assert detail["decisions"] == []


def test_get_run_detail_unknown_id_raises_keyerror(tmp_path):
    with pytest.raises(KeyError):
        runs_api.get_run_detail(tmp_path / "runs", "does-not-exist")


def test_get_report_markdown_and_missing(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    rep = runs_api.get_report(runs, "20260102-000000-bbbb")
    assert rep["available"] is True and "## Source registry" in rep["markdown"]
    assert rep["sources"]["src-a"]["excerpts"] == ["X raised Y by 12%."]
    _make_run(runs, "20260101-000000-aaaa")
    assert runs_api.get_report(runs, "20260101-000000-aaaa")["available"] is False


def test_run_id_validation_rejects_path_traversal(tmp_path):
    for bad in ["../etc", "a/b", "..\\x", "a b", ""]:
        assert runs_api.is_valid_run_id(bad) is False
    assert runs_api.is_valid_run_id("20260102-000000-bbbb") is True


def test_run_id_validation_rejects_trailing_newline():
    # re.match would let "...-bbbb\n" through ($ matches before a final \n);
    # the validator must anchor with fullmatch semantics.
    assert runs_api.is_valid_run_id("20260102-000000-bbbb\n") is False


def _client(runs_dir, env_path=None):
    from starlette.testclient import TestClient
    from src.webui.app import create_app
    if env_path is None:
        env_path = runs_dir.parent / ".env"  # empty tmp .env — never the real one
    return TestClient(create_app(runs_dir=runs_dir, env_path=env_path))


def test_api_runs_list_route(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    c = _client(runs)
    r = c.get("/api/runs")
    assert r.status_code == 200
    assert r.json()[0]["run_id"] == "20260102-000000-bbbb"


def test_api_run_detail_route_and_404(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260101-000000-aaaa")
    c = _client(runs)
    assert c.get("/api/runs/20260101-000000-aaaa").json()["meta"]["profile"] == "general"
    assert c.get("/api/runs/does-not-exist").status_code == 404
    assert c.get("/api/runs/..%2f..%2fetc").status_code in (400, 404)


def test_api_report_routes(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    c = _client(runs)
    assert "Source registry" in c.get("/api/runs/20260102-000000-bbbb/report").json()["markdown"]
    pdf = c.get("/api/runs/20260102-000000-bbbb/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"


def test_report_md_download_route(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    c = _client(runs)
    r = c.get("/api/runs/20260102-000000-bbbb/report.md")
    assert r.status_code == 200
    assert "Source registry" in r.text
    assert r.headers["content-type"].startswith("text/markdown")
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "true-research-20260102-000000-bbbb.md" in cd


def test_report_md_404_when_pending(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260101-000000-aaaa")  # no REPORT.md yet
    c = _client(runs)
    assert c.get("/api/runs/20260101-000000-aaaa/report.md").status_code == 404
    assert c.get("/api/runs/does-not-exist/report.md").status_code == 404


def test_index_html_served(tmp_path):
    c = _client(tmp_path / "runs")
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_no_route_leaks_secrets(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    c = _client(runs)
    bodies = [
        c.get("/api/runs").text,
        c.get("/api/runs/20260102-000000-bbbb").text,
        c.get("/api/runs/20260102-000000-bbbb/report").text,
    ]
    for b in bodies:
        low = b.lower()
        for needle in ["api_key", "api-key", "secret", "auth_token", "sk-ant", "authorization", "os.environ"]:
            assert needle not in low, f"possible secret surface: {needle!r}"

    keys_body = c.get("/api/keys").text.lower()
    for needle in ["sk-ant", "authorization", "os.environ", "value"]:
        assert needle not in keys_body, f"possible secret surface: {needle!r}"


def test_launch_validates_and_spawns(tmp_path, monkeypatch):
    import src.webui.launch_api as la
    spawned = {}
    monkeypatch.setattr(la, "_spawn_detached",
                        lambda argv, log_path: spawned.update(argv=argv, log=str(log_path)) or 4321)
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-deep\n", encoding="utf-8")
    c = _client(tmp_path / "runs", env_path=env)
    r = c.post("/api/runs", json={"question": "Is the sky blue?",
                                  "preset": "comprehensive",
                                  "max_budget_usd": 5, "max_wall_hours": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["launched"] is True and body["pid"] == 4321
    assert body["backend"] == "cheap"
    argv = spawned["argv"]
    assert "--question-file" in argv and "--comprehensive" in argv and "--verify" in argv
    assert "--cheap" in argv and "--gate" in argv and "opus" in argv
    assert "--max-budget-usd" in argv and "5.0" in argv
    assert "Is the sky blue?" not in argv


def test_launch_preset_matrix_backend_fallback(tmp_path, monkeypatch):
    """quick/comprehensive x deepseek-present/absent -> exact flag bundles."""
    import src.webui.launch_api as la
    calls = []
    monkeypatch.setattr(la, "_spawn_detached", lambda argv, log_path: calls.append(argv) or 1)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    env_with = tmp_path / "with.env"
    env_with.write_text("DEEPSEEK_API_KEY=sk-deep\n", encoding="utf-8")
    env_without = tmp_path / "without.env"
    env_without.write_text("", encoding="utf-8")

    expectations = [
        (env_with, "quick", "cheap", ["--cheap", "--gate", "opus"]),
        (env_with, "comprehensive", "cheap",
         ["--cheap", "--gate", "opus", "--comprehensive", "--verify"]),
        (env_without, "quick", "anthropic", []),
        (env_without, "comprehensive", "anthropic", ["--comprehensive", "--verify"]),
    ]
    for env, preset, backend, flags in expectations:
        calls.clear()
        c = _client(tmp_path / "runs", env_path=env)
        r = c.post("/api/runs", json={"question": "q?", "preset": preset})
        assert r.status_code == 200, (preset, env.name)
        assert r.json()["backend"] == backend
        argv = calls[0]
        assert argv[0] == "--question-file"
        assert argv[2:] == flags, (preset, env.name, argv)


def test_launch_rejects_empty_question(tmp_path):
    c = _client(tmp_path / "runs")
    assert c.post("/api/runs", json={"question": "   "}).status_code == 422


def test_launch_rejects_nonfinite_and_negative_budget(tmp_path):
    # Negative/zero budgets (and inf/nan, blocked by allow_inf_nan=False)
    # would disable the budget circuit breaker — must be a 422, never a spawn.
    c = _client(tmp_path / "runs")
    for bad in [{"question": "q", "max_budget_usd": -5},
                {"question": "q", "max_wall_hours": 0}]:
        assert c.post("/api/runs", json=bad).status_code == 422


def test_launch_rejects_unknown_preset(tmp_path):
    c = _client(tmp_path / "runs")
    for old in ["standard", "exhaustive", "cheap", "bogus"]:
        assert c.post("/api/runs", json={"question": "ok", "preset": old}).status_code == 422


def test_post_routes_reject_cross_origin(tmp_path, monkeypatch):
    """Drive-by CSRF defense: a browser on evil.com POSTing to the local
    server sends Origin: https://evil.com — must be 403, never a spawn or a
    key write. Same-origin/localhost Origins (any port) and absent Origin
    (curl, tests) pass."""
    import src.webui.launch_api as la
    monkeypatch.setattr(la, "_spawn_detached", lambda argv, log_path: 1)
    c = _client(tmp_path / "runs")
    evil = {"Origin": "https://evil.com"}
    assert c.post("/api/runs", json={"question": "q"}, headers=evil).status_code == 403
    assert c.post("/api/keys", json={"name": "SERPER_API_KEY", "value": "x"},
                  headers=evil).status_code == 403
    for ok_origin in ["http://127.0.0.1:8787", "http://localhost:8787", "http://[::1]:8787"]:
        r = c.post("/api/runs", json={"question": "q"},
                   headers={"Origin": ok_origin})
        assert r.status_code == 200, ok_origin
    assert c.post("/api/keys", json={"name": "SERPER_API_KEY", "value": "x"}).status_code == 200
    for bad in ["null", "http://localhost.evil.com", "http://127.0.0.1.evil.com"]:
        assert c.post("/api/keys", json={"name": "SERPER_API_KEY", "value": "x"},
                      headers={"Origin": bad}).status_code == 403, bad


def test_api_keys_non_dict_body_not_echoed(tmp_path):
    # FastAPI's default validation echoes non-dict bodies back; the handler
    # must accept Any and reject non-dicts itself so a pasted secret sent as
    # a bare string is never reflected.
    c = _client(tmp_path / "runs")
    r = c.post("/api/keys", json="sk-bare-secret-body")
    assert r.status_code == 422
    assert "sk-bare-secret-body" not in r.text


def test_frontend_assets_served_and_wired(tmp_path):
    c = _client(tmp_path / "runs")
    html = c.get("/").text
    assert 'id="app"' in html
    assert "/static/app.js" in html and "/static/style.css" in html
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/style.css").status_code == 200
    assert c.get("/static/vendor/marked.min.js").status_code == 200
