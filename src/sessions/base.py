"""Shared session plumbing: the SessionResult contract, typed session errors
(CLAUDE.md §6), and per-session endpoint env resolution (§1).

Phase 1 note: the Agent SDK wrapper (spawn-one-fresh-session, max_turns +
per-session budget enforcement, usage capture) lands here in Phase 2. Nothing
in this module imports the SDK yet — Phase 1 makes zero LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.errors import EngineError
from src.settings import SessionType, Settings


class SessionError(EngineError):
    """Base for failures inside a session module."""


class PlanningError(SessionError):
    pass


class WorkerError(SessionError):
    pass


class EvalError(SessionError):
    pass


class SynthesisError(SessionError):
    pass


@dataclass(frozen=True)
class SessionResult:
    """What every session hands back to the driver for the ledger."""

    session_type: SessionType
    model: str
    endpoint: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    usd: float
    wall_seconds: float
    summary: str


def resolve_endpoint_env(settings: Settings, role_name: str) -> dict[str, str]:
    """Env vars to inject into ONE spawned session via ClaudeAgentOptions.env.

    Verified mechanism (docs/SDK_NOTES.md): options.env merges over the
    inherited process env per subprocess; the CLI honors ANTHROPIC_API_KEY
    (first-party) and ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN (any other
    endpoint). Secrets come from Settings — never from this process's environ.
    """
    role = settings.roles.get(role_name)
    if role is None:
        raise EngineError(f"unknown role {role_name!r}")
    endpoint = settings.endpoints[role.endpoint]
    secret = settings.secret_for(role.endpoint).get_secret_value()
    if endpoint.base_url is None:
        return {"ANTHROPIC_API_KEY": secret}
    return {"ANTHROPIC_BASE_URL": endpoint.base_url, "ANTHROPIC_AUTH_TOKEN": secret}
