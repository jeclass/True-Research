"""Shared session plumbing (CLAUDE.md §6): the SessionResult contract, typed
session errors, per-session endpoint env resolution (§1), and the Agent SDK
wrapper that spawns ONE fresh amnesiac session.

Amnesia guarantees enforced here for every spawn (invariant 1):
  - explicit system_prompt string (never the Claude Code preset)
  - setting_sources=[] (no user/project settings, no CLAUDE.md leakage)
  - cwd = the run directory, fresh session id, no resume/continue
Breakers enforced here (invariant 4): max_turns and per-session max_budget_usd
from config. The SDK import is lazy so stub-backend runs never touch it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.errors import EngineError
from src.ledger import Ledger
from src.runspace import Runspace
from src.settings import SessionType, Settings
from src.state import LedgerEntry


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


_ERROR_BY_TYPE: dict[SessionType, type[SessionError]] = {
    "initializer": PlanningError,
    "worker": WorkerError,
    "evaluator": EvalError,
    "synthesizer": SynthesisError,
}


@dataclass(frozen=True)
class SessionResult:
    """What every session hands back to the driver for display/summary.
    Ledger entries are recorded by the session layer itself, so a session
    that fails AFTER spending tokens still gets accounted."""

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


OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True)
class Spawn:
    """Outcome of one SDK session: parsed structured output + the metrics that
    were written to the ledger."""

    structured: Any
    result_text: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    usd: float
    wall_seconds: float
    num_turns: int


def run_role_session(
    *,
    run: Runspace,
    settings: Settings,
    ledger: Ledger,
    cycle: int,
    session_type: SessionType,
    role: str,
    system_prompt: str,
    user_prompt: str,
    tools: list[str],
    output_model: type[OutputT] | None = None,
) -> Spawn:
    """Spawn ONE fresh Agent SDK session for `role`, record its spend in the
    ledger (success OR failure), and return validated structured output."""
    # Lazy import: Phase 1 paths and the stub backend stay SDK-free.
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    from claude_agent_sdk import ClaudeSDKError

    error_cls = _ERROR_BY_TYPE[session_type]
    role_cfg = settings.roles[role]
    env = resolve_endpoint_env(settings, role)

    output_format = None
    if output_model is not None:
        output_format = {"type": "json_schema", "schema": output_model.model_json_schema()}

    options = ClaudeAgentOptions(
        model=role_cfg.model,
        system_prompt=system_prompt,
        tools=list(tools),
        allowed_tools=list(tools),
        permission_mode="dontAsk",  # anything not pre-approved is denied, fail-closed
        max_turns=role_cfg.max_turns,
        max_budget_usd=settings.session.max_budget_usd_per_session,
        cwd=str(run.root),
        env=env,
        setting_sources=[],
        output_format=output_format,
    )

    async def _consume() -> ResultMessage:
        final: ResultMessage | None = None
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, ResultMessage):
                final = message
        if final is None:
            raise error_cls(
                f"{session_type} session ended without a result message"
            )
        return final

    started = time.monotonic()
    try:
        result = asyncio.run(_consume())
    except ClaudeSDKError as exc:
        raise error_cls(f"{session_type} session transport failure: {exc}") from exc
    wall = time.monotonic() - started

    usage = result.usage or {}
    cached = int(usage.get("cache_read_input_tokens") or 0) + int(
        usage.get("cache_creation_input_tokens") or 0
    )
    metrics = dict(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cached_tokens=cached,
        usd=float(result.total_cost_usd or 0.0),
        wall_seconds=wall,
    )
    # Record spend FIRST — a failed session still burned tokens (SDK_NOTES:
    # error results carry usage too).
    ledger.record(
        LedgerEntry(
            cycle=cycle,
            session_type=session_type,
            model=role_cfg.model,
            endpoint=role_cfg.endpoint,
            **metrics,
        )
    )

    if result.is_error or result.subtype != "success":
        detail = "; ".join(result.errors or []) or (result.result or "no detail")
        status = f" (api_error_status={result.api_error_status})" if result.api_error_status else ""
        raise error_cls(
            f"{session_type} session failed: subtype={result.subtype}{status}: {detail}"
        )

    structured: Any = None
    if output_model is not None:
        if result.structured_output is None:
            raise error_cls(
                f"{session_type} session returned no structured output "
                f"(expected {output_model.__name__}); raw result: "
                f"{(result.result or '')[:500]}"
            )
        try:
            structured = output_model.model_validate(result.structured_output)
        except ValidationError as exc:
            raise error_cls(
                f"{session_type} structured output failed validation:\n{exc}"
            ) from exc

    return Spawn(
        structured=structured,
        result_text=result.result or "",
        num_turns=result.num_turns,
        **metrics,
    )
