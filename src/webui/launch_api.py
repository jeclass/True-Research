"""Launch API — the ONE mutating route: kick off a new research run.

SECURITY (this endpoint is the injection surface): the user-supplied question
text must NEVER be interpolated into the driver's argv. It is written to a
file under runs/.webui_pending/ and passed via --question-file only. All CLI
flags are built from a FIXED ALLOWLIST derived from validated Pydantic
fields — never free-form strings from the client. The assembled argv is
validated by calling driver.parse_args(...) before anything is spawned;
argparse rejection (SystemExit) is converted to HTTP 422.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator


class LaunchRequest(BaseModel):
    question: str
    preset: Literal["standard", "comprehensive", "exhaustive", "cheap"] = "standard"
    verify: bool = False
    # gt=0 + allow_inf_nan=False: a zero/negative/inf/nan cap would disable
    # the budget/wall-clock circuit breakers (invariant 4).
    max_budget_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_wall_hours: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be empty")
        return v


_PRESET_FLAGS: dict[str, list[str]] = {
    "standard": [],
    "comprehensive": ["--comprehensive"],
    "exhaustive": ["--exhaustive"],
    "cheap": ["--cheap", "--gate", "opus"],
}


def _spawn_detached(argv: list[str], log_path: Path) -> int:
    """Thin wrapper around src.launcher.spawn_detached — the monkeypatch seam
    for tests. Lazy import keeps this module's import light."""
    from src.launcher import spawn_detached

    return spawn_detached(argv, log_path=log_path)


def build_driver_args(req: LaunchRequest, question_file: Path) -> list[str]:
    """Assemble the driver argv from a FIXED ALLOWLIST of flags derived from
    validated fields. The question text itself never appears here — only the
    path to the file it was written to."""
    args: list[str] = ["--question-file", str(question_file)]
    args += _PRESET_FLAGS[req.preset]
    if req.verify:
        args += ["--verify"]
    if req.max_budget_usd is not None:
        args += ["--max-budget-usd", str(float(req.max_budget_usd))]
    if req.max_wall_hours is not None:
        args += ["--max-wall-hours", str(float(req.max_wall_hours))]
    return args


def launch(req: LaunchRequest, runs_dir: Path) -> dict:
    pending_dir = runs_dir / ".webui_pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=pending_dir, encoding="utf-8"
    ) as tf:
        tf.write(req.question)
        question_file = Path(tf.name)
    # Intentionally NOT deleting question_file: the detached driver reads it
    # asynchronously at startup, so removing it here risks a race. It's a
    # small file under runs/ (gitignored).

    args = build_driver_args(req, question_file)

    import driver

    try:
        driver.parse_args(args)
    except SystemExit as exc:
        raise HTTPException(status_code=422, detail="invalid launch options") from exc

    log_path = runs_dir / "_webui_launch.log"
    pid = _spawn_detached(args, log_path)
    return {"launched": True, "pid": pid}
