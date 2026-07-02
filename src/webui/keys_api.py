"""Keys API — dashboard management of the API keys in .env.

SECURITY: this module reads .env ONLY to answer "is this key set?" (a
boolean) and WRITES values the operator submits. No function returns, logs,
or embeds a key VALUE in any response — responses carry names + booleans
only. The allowlist is fixed: arbitrary env names can never be written.
.env writing is conservative — only the matching `NAME=` line is replaced;
every other line (comments, unrelated vars) is preserved byte-for-byte —
and atomic (temp file + os.replace) so a crash can't truncate .env.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, field_validator

# name -> human "used for" copy shown in the Keys panel.
KEY_ALLOWLIST: dict[str, str] = {
    "ANTHROPIC_API_KEY": (
        "Required for all presets — judgment roles and the terminal gate."
    ),
    "DEEPSEEK_API_KEY": (
        "Cheap backend (volume + grounded roles) — unlocks the $1–5 run costs."
    ),
    "SERPER_API_KEY": (
        "Optional — broader Google-index search; DuckDuckGo fallback without it."
    ),
}


class SetKeyRequest(BaseModel):
    name: str
    value: str

    @field_validator("name")
    @classmethod
    def _name_allowlisted(cls, v: str) -> str:
        if v not in KEY_ALLOWLIST:
            raise ValueError(f"unknown key name (allowed: {sorted(KEY_ALLOWLIST)})")
        return v

    @field_validator("value")
    @classmethod
    def _value_sane(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("value must not be empty")
        if any(ord(ch) < 32 for ch in v):
            raise ValueError("value must not contain newlines or control characters")
        return v


def is_key_set(name: str, env_path: Path) -> bool:
    """Same precedence as settings.py: .env file first, os.environ fallback
    (so CI-injected keys count). Returns a boolean — never the value."""
    value = dotenv_values(str(env_path)).get(name) or os.environ.get(name)
    return bool(value)


def key_status(env_path: Path) -> list[dict]:
    return [
        {"name": name, "set": is_key_set(name, env_path), "used_for": used_for}
        for name, used_for in KEY_ALLOWLIST.items()
    ]


def set_key(req: SetKeyRequest, env_path: Path) -> dict:
    """Write NAME=value into .env: replace the existing NAME= line in place,
    else append. Atomic via temp file + os.replace in the same directory."""
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    prefix = req.name + "="
    new_line = f"{req.name}={req.value}"
    replaced = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(prefix):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(env_path.parent), suffix=".env.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tf:
            tf.write("\n".join(lines) + "\n")
        os.replace(tmp_name, env_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return {"name": req.name, "set": True}
