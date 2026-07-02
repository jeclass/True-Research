"""Read-only reader layer over runs/<id>/ state directories for the web UI.

SECURITY: this module is a read-only view over on-disk run-state files. It
must NEVER import Settings, read .env/os.environ, or expose any secret. It
reads only: run.json, ledger.json, PROGRESS.md, open_questions.yaml,
sources.json, findings/*.md, REPORT.md/.pdf. Every run_id is validated with
RUN_ID_RE before it is ever used to build a filesystem path (path-traversal
guard) — see is_valid_run_id().
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from src.state import parse_ledger, parse_run_meta

RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")

_REPORT_FILE = "REPORT.md"
_REPORT_PDF_FILE = "REPORT.pdf"
_DECISIONS_HEADING = "## DECISIONS"


def is_valid_run_id(run_id: str) -> bool:
    # fullmatch, not match: `$` in a match() would accept a trailing newline.
    return bool(RUN_ID_RE.fullmatch(run_id))


def _spend_usd(run_dir: Path) -> float:
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.exists():
        return 0.0
    try:
        entries = parse_ledger(ledger_path.read_text(encoding="utf-8")).root
    except Exception:
        return 0.0
    return sum(e.usd for e in entries)


def _ledger_entries(run_dir: Path):
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.exists():
        return []
    try:
        return parse_ledger(ledger_path.read_text(encoding="utf-8")).root
    except Exception:
        return []


def _resolve_run_dir(runs_dir: Path, run_id: str) -> Path:
    """Validate run_id, then confirm the run exists. Raises KeyError(run_id)
    on anything invalid or missing — never builds a path from a bad id."""
    if not is_valid_run_id(run_id):
        raise KeyError(run_id)
    run_dir = runs_dir / run_id
    if not (run_dir / "run.json").exists():
        raise KeyError(run_id)
    return run_dir


def list_runs(runs_dir: Path) -> list[dict]:
    if not runs_dir.exists():
        return []
    out = []
    for meta_path in runs_dir.glob("*/run.json"):
        run_dir = meta_path.parent
        try:
            meta = parse_run_meta(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "run_id": meta.run_id,
            "question": meta.question,
            "profile": meta.profile,
            "status": meta.status,
            "finish_reason": meta.finish_reason,
            "last_cycle": meta.last_cycle,
            "spend_usd": _spend_usd(run_dir),
            "has_report": (run_dir / _REPORT_FILE).exists(),
            "created_at": meta.created_at.isoformat(),
        })
    out.sort(key=lambda r: r["run_id"], reverse=True)
    return out


def _read_questions(run_dir: Path) -> list[dict]:
    path = run_dir / "open_questions.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return [
            {
                "id": q["id"],
                "question": q["question"],
                "status": q["status"],
                "priority": q["priority"],
            }
            for q in data
        ]
    except Exception:
        return []


def _read_findings(run_dir: Path) -> list[dict]:
    findings_dir = run_dir / "findings"
    if not findings_dir.exists():
        return []
    out = []
    for path in sorted(findings_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            if not lines or lines[0].strip() != "---":
                continue
            end = next(
                i for i, line in enumerate(lines[1:], start=1)
                if line.strip() == "---"
            )
            meta = yaml.safe_load("\n".join(lines[1:end]))
            if not isinstance(meta, dict):
                continue
            out.append({
                "slug": path.stem,
                "question_id": meta["question_id"],
                "confidence": meta["confidence"],
                "verification_status": meta.get("verification_status", "unverified"),
                "source_ids": meta.get("source_ids", []),
            })
        except Exception:
            continue
    return out


def _read_sources(run_dir: Path) -> dict:
    path = run_dir / "sources.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_decisions(run_dir: Path) -> list[str]:
    path = run_dir / "PROGRESS.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    head, sep, tail = text.partition(_DECISIONS_HEADING)
    if not sep:
        return []
    return [
        line.strip() for line in tail.splitlines()
        if line.strip().startswith("- ")
    ]


def get_run_detail(runs_dir: Path, run_id: str) -> dict:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    meta = parse_run_meta((run_dir / "run.json").read_text(encoding="utf-8"))

    ledger_by_type: dict[str, int] = {}
    for entry in _ledger_entries(run_dir):
        ledger_by_type[entry.session_type] = ledger_by_type.get(entry.session_type, 0) + 1

    return {
        "meta": meta.model_dump(mode="json"),
        "spend_usd": _spend_usd(run_dir),
        "ledger_by_type": ledger_by_type,
        "questions": _read_questions(run_dir),
        "findings": _read_findings(run_dir),
        "sources": _read_sources(run_dir),
        "decisions": _read_decisions(run_dir),
    }


def get_report(runs_dir: Path, run_id: str) -> dict:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    report_path = run_dir / _REPORT_FILE
    if not report_path.exists():
        return {"available": False, "markdown": None, "sources": {}}
    return {
        "available": True,
        "markdown": report_path.read_text(encoding="utf-8"),
        "sources": _read_sources(run_dir),
    }


def report_pdf_path(runs_dir: Path, run_id: str) -> Path | None:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    pdf_path = run_dir / _REPORT_PDF_FILE
    return pdf_path if pdf_path.exists() else None


def report_md_path(runs_dir: Path, run_id: str) -> Path | None:
    run_dir = _resolve_run_dir(runs_dir, run_id)
    md_path = run_dir / _REPORT_FILE
    return md_path if md_path.exists() else None
