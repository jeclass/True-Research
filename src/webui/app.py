"""FastAPI app exposing the read-only run-state layer (src/webui/runs_api.py)
plus the state-changing routes: POST /api/runs launches a research run
(src/webui/launch_api.py) and POST /api/keys writes a key to .env
(src/webui/keys_api.py). Both POSTs enforce a localhost-origin check
(_require_local_origin) as drive-by CSRF defense.

SECURITY: the GET routes are a thin read-only view over runs/<id>/ state
files and must NEVER serialize Settings, .env, os.environ, or any SecretStr
— see tests/test_webui.py::test_no_route_leaks_secrets. They do NOT import
driver or Settings. The POST /api/runs route is the injection surface: it
delegates entirely to src.webui.launch_api, which writes the question to a
file (never argv) and validates the assembled args via driver.parse_args
before spawning. See launch_api.py for the full security contract.

Intended deployment: bind 127.0.0.1 only, no auth by design — this is a
localhost single-operator tool, not a multi-tenant or internet-facing service.
The /api/keys routes return names + set-booleans only; values are write-only
(see src/webui/keys_api.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from src.webui import keys_api, launch_api, runs_api

_STATIC_DIR = Path(__file__).parent / "static"
_FALLBACK_INDEX_HTML = "<!doctype html><meta charset=utf-8><title>True Research</title>"

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _require_local_origin(request: Request) -> None:
    """CSRF defense for the localhost server: browsers attach an Origin
    header to cross-origin (and modern same-origin) POSTs. Absent Origin
    (curl, tests, older same-origin fetch) is allowed — the threat is a
    hostile WEBSITE, which cannot suppress Origin. Non-local Origin -> 403."""
    origin = request.headers.get("origin")
    if origin is None:
        return
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        host = None
    if host not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="cross-origin request rejected")


def create_app(runs_dir: Path, env_path: Path = Path(".env")) -> FastAPI:
    app = FastAPI(title="True Research Web UI")

    _STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/api/runs")
    def api_list_runs():
        return runs_api.list_runs(runs_dir)

    @app.post("/api/runs", dependencies=[Depends(_require_local_origin)])
    def api_launch_run(req: launch_api.LaunchRequest):
        return launch_api.launch(req, runs_dir, env_path=env_path)

    @app.get("/api/keys")
    def api_keys_status():
        return keys_api.key_status(env_path)

    @app.post("/api/keys", dependencies=[Depends(_require_local_origin)])
    def api_keys_set(payload: Any = Body(...)):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="body must be a JSON object")
        try:
            req = keys_api.SetKeyRequest.model_validate(payload)
        except ValidationError as exc:
            # Redacted 422: field + message only, never the submitted input.
            detail = [
                {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()
            ]
            raise HTTPException(status_code=422, detail=detail)
        return keys_api.set_key(req, env_path)

    @app.get("/api/runs/{run_id}")
    def api_run_detail(run_id: str):
        if "/" in run_id or "\\" in run_id:
            raise HTTPException(status_code=400, detail="invalid run_id")
        try:
            return runs_api.get_run_detail(runs_dir, run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")

    @app.get("/api/runs/{run_id}/report")
    def api_report(run_id: str):
        if "/" in run_id or "\\" in run_id:
            raise HTTPException(status_code=400, detail="invalid run_id")
        try:
            return runs_api.get_report(runs_dir, run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")

    @app.get("/api/runs/{run_id}/report.pdf")
    def api_report_pdf(run_id: str):
        if "/" in run_id or "\\" in run_id:
            raise HTTPException(status_code=400, detail="invalid run_id")
        try:
            pdf_path = runs_api.report_pdf_path(runs_dir, run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        if pdf_path is None:
            raise HTTPException(status_code=404, detail="report.pdf not available")
        return FileResponse(pdf_path, media_type="application/pdf")

    @app.get("/")
    def index():
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse(_FALLBACK_INDEX_HTML)

    return app
