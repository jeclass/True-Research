"""Shared session plumbing (CLAUDE.md §6): the SessionResult contract, typed
session errors, per-session endpoint env resolution (§1), and the Agent SDK
wrapper that spawns ONE fresh amnesiac session.

Amnesia guarantees enforced here for every spawn (invariant 1):
  - explicit system_prompt string (never the Claude Code preset)
  - setting_sources=[] (no user/project settings, no CLAUDE.md leakage)
  - cwd = the run directory, fresh session id, no resume/continue
Breakers enforced here (invariant 4): max_turns and per-session max_budget_usd
from config. The SDK import is lazy so stub-backend runs never touch it.

The core spawn is async (run_role_session_async) because reader sessions are
spawned from inside the worker's MCP tool handlers, i.e. while the worker's
own event loop is running. run_role_session is the sync wrapper for the
driver-called session modules.
"""

from __future__ import annotations

import asyncio
import json
import re
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


class ReaderError(SessionError):
    pass


_ERROR_BY_TYPE: dict[SessionType, type[SessionError]] = {
    "initializer": PlanningError,
    "worker": WorkerError,
    "evaluator": EvalError,
    "synthesizer": SynthesisError,
    "reader": ReaderError,
    "judge": EvalError,
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

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_prompted_json(text: str, output_model: type[OutputT]) -> OutputT:
    """Parse a JSON object out of a model's plain-text reply (the structured
    path for endpoints that don't implement output_format, e.g. local Ollama).
    Tolerates code fences and surrounding prose; everything else fails loudly."""
    candidate = text.strip()
    fenced = _JSON_FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        return output_model.model_validate(json.loads(candidate))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"prompted-JSON parse failed: {exc}") from exc


def json_response_instructions(output_model: type[BaseModel]) -> str:
    """Appended to prompts on endpoints without API-side structured output."""
    schema = json.dumps(output_model.model_json_schema(), indent=2)
    return (
        "\n\n# Response format (MANDATORY)\n"
        "Respond with a single JSON object and NOTHING else — no prose before "
        "or after, no markdown fences. It must validate against this JSON "
        f"schema:\n{schema}\n"
    )


# HTTP statuses worth retrying (CLAUDE.md §8 Phase 5). Permanent failures
# (4xx auth/validation, model errors) are never retried.
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})


class _TransientSpawnFailure(Exception):
    """Internal marker: this spawn attempt failed transiently; retry."""


def is_transient_result(is_error: bool, subtype: str, api_error_status: int | None) -> bool:
    return bool(
        (is_error or subtype != "success")
        and api_error_status in TRANSIENT_HTTP_STATUSES
    )


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


def finalize_metrics(
    usage: dict[str, Any] | None,
    total_cost_usd: float | None,
    endpoint_cfg: Any,
    wall_seconds: float,
) -> dict[str, Any]:
    """Token/cost numbers for the ledger. Cost precedence:
    1. endpoint.price_per_mtok configured -> computed from token counts
       (cached tokens billed at the input rate — conservative, breaker-safe).
       This is how PAID non-first-party endpoints get real spend.
    2. first-party endpoint (base_url None) -> the CLI's client-side estimate.
    3. otherwise (free local) -> usd 0 per §1, tokens still recorded."""
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cached = int(usage.get("cache_read_input_tokens") or 0) + int(
        usage.get("cache_creation_input_tokens") or 0
    )
    if endpoint_cfg.price_per_mtok is not None:
        price = endpoint_cfg.price_per_mtok
        usd = (
            (input_tokens + cached) * price.input + output_tokens * price.output
        ) / 1_000_000
    elif endpoint_cfg.base_url is None:
        usd = float(total_cost_usd or 0.0)
    else:
        usd = 0.0
    return dict(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached,
        usd=usd,
        wall_seconds=wall_seconds,
    )


async def run_role_session_async(
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
    mcp_servers: dict[str, Any] | None = None,
    extra_allowed_tools: list[str] | None = None,
) -> Spawn:
    """Spawn ONE fresh Agent SDK session for `role`, record its spend in the
    ledger (success OR failure), and return validated structured output.

    Structured output path is endpoint-dependent: first-party endpoints get
    API-enforced output_format; non-first-party endpoints (local Ollama,
    gateways) get prompted JSON parsed engine-side, since output_format
    support cannot be assumed there.
    """
    # Lazy import: Phase 1 paths and the stub backend stay SDK-free.
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKError, ResultMessage, query

    error_cls = _ERROR_BY_TYPE[session_type]
    role_cfg = settings.roles[role]
    endpoint_cfg = settings.endpoints[role_cfg.endpoint]
    endpoint_is_local = endpoint_cfg.base_url is not None
    env = resolve_endpoint_env(settings, role)

    structured_via_api = output_model is not None and not endpoint_is_local
    output_format = None
    if structured_via_api:
        output_format = {"type": "json_schema", "schema": output_model.model_json_schema()}
    elif output_model is not None:
        user_prompt = user_prompt + json_response_instructions(output_model)

    options = ClaudeAgentOptions(
        model=role_cfg.model,
        system_prompt=system_prompt,
        tools=list(tools),
        allowed_tools=list(tools) + list(extra_allowed_tools or []),
        permission_mode="dontAsk",  # anything not pre-approved is denied, fail-closed
        max_turns=role_cfg.max_turns,
        max_budget_usd=settings.session.max_budget_usd_per_session,
        cwd=str(run.root),
        env=env,
        setting_sources=[],
        output_format=output_format,
        mcp_servers=mcp_servers or {},
    )

    from claude_agent_sdk import CLIConnectionError
    from tenacity import (
        AsyncRetrying,
        RetryError,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    async def _attempt() -> tuple[ResultMessage, dict[str, Any]]:
        started = time.monotonic()
        final: ResultMessage | None = None
        try:
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, ResultMessage):
                    final = message
        except CLIConnectionError as exc:
            raise _TransientSpawnFailure(f"transport: {exc}") from exc
        except ClaudeSDKError as exc:
            raise error_cls(f"{session_type} session transport failure: {exc}") from exc
        if final is None:
            raise _TransientSpawnFailure("session ended without a result message")
        wall = time.monotonic() - started

        metrics = finalize_metrics(final.usage, final.total_cost_usd, endpoint_cfg, wall)
        # Record spend on EVERY attempt — a failed/retried session still
        # burned tokens (SDK_NOTES: error results carry usage too).
        ledger.record(
            LedgerEntry(
                cycle=cycle,
                session_type=session_type,
                model=role_cfg.model,
                endpoint=role_cfg.endpoint,
                **metrics,
            )
        )

        if final.is_error or final.subtype != "success":
            detail = "; ".join(final.errors or []) or (final.result or "no detail")
            status = (
                f" (api_error_status={final.api_error_status})"
                if final.api_error_status
                else ""
            )
            message = (
                f"{session_type} session failed: subtype={final.subtype}{status}: {detail}"
            )
            if is_transient_result(final.is_error, final.subtype, final.api_error_status):
                raise _TransientSpawnFailure(message)
            raise error_cls(message)
        return final, metrics

    retry_cfg = settings.retry
    try:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_TransientSpawnFailure),
            stop=stop_after_attempt(retry_cfg.attempts),
            wait=wait_exponential(
                multiplier=retry_cfg.base_delay_seconds,
                max=retry_cfg.max_delay_seconds,
            ),
            reraise=False,
        ):
            with attempt:
                if attempt.retry_state.attempt_number > 1:
                    run.log(
                        f"{session_type} (cycle {cycle}): transient failure — "
                        f"retry {attempt.retry_state.attempt_number}/{retry_cfg.attempts}"
                    )
                final, metrics = await _attempt()
    except RetryError as exc:
        last = exc.last_attempt.exception()
        raise error_cls(
            f"{session_type} session failed after {retry_cfg.attempts} attempts "
            f"(transient): {last}"
        ) from exc

    structured: Any = None
    if output_model is not None:
        if structured_via_api:
            if final.structured_output is None:
                raise error_cls(
                    f"{session_type} session returned no structured output "
                    f"(expected {output_model.__name__}); raw result: "
                    f"{(final.result or '')[:500]}"
                )
            try:
                structured = output_model.model_validate(final.structured_output)
            except ValidationError as exc:
                raise error_cls(
                    f"{session_type} structured output failed validation:\n{exc}"
                ) from exc
        else:
            try:
                structured = parse_prompted_json(final.result or "", output_model)
            except ValueError as exc:
                raise error_cls(
                    f"{session_type} session ({role_cfg.model} via "
                    f"{role_cfg.endpoint}) did not return parseable JSON — the "
                    f"model may be unsuitable for this role (§1). {exc}"
                ) from exc

    return Spawn(
        structured=structured,
        result_text=final.result or "",
        num_turns=final.num_turns,
        **metrics,
    )


def run_role_session(**kwargs: Any) -> Spawn:
    """Sync wrapper for driver-called session modules (one event loop per
    session; readers inside the worker use the async core directly)."""
    return asyncio.run(run_role_session_async(**kwargs))
