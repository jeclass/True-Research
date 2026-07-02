"""FastAPI app exposing the read-only run-state layer (src/webui/runs_api.py).

SECURITY: this app is a thin read-only view over runs/<id>/ state files. It
must NEVER serialize Settings, .env, os.environ, or any SecretStr — see
tests/test_webui.py::test_no_route_leaks_secrets. Routes expose run-state
files ONLY. Do NOT import driver or Settings here.

Intended deployment: bind 127.0.0.1 only, no auth by design — this is a
localhost single-operator tool, not a multi-tenant or internet-facing service.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.webui import runs_api

_STATIC_DIR = Path(__file__).parent / "static"
_FALLBACK_INDEX_HTML = "<!doctype html><meta charset=utf-8><title>True Research</title>"


def create_app(runs_dir: Path) -> FastAPI:
    app = FastAPI(title="True Research Web UI")

    _STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/api/runs")
    def api_list_runs():
        return runs_api.list_runs(runs_dir)

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
