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
        env = {"ANTHROPIC_API_KEY": secret}
    else:
        env = {"ANTHROPIC_BASE_URL": endpoint.base_url, "ANTHROPIC_AUTH_TOKEN": secret}
    # Volume endpoints (Flash reader/query-gen/compose) extract, they don't
    # reason — tell the CLI to request no thinking budget, so Flash stops
    # emitting ~16k-token reasoning per read (the $0.16 outlier cost spikes).
    if endpoint.disable_thinking:
        env["MAX_THINKING_TOKENS"] = "0"
    return env


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


def _transport_error(error_cls: type[SessionError], message: str) -> SessionError:
    """Build a typed session error marked TRANSPORT-class: the ENDPOINT failed
    (SDK/connection/HTTP failure, session died without a ResultMessage, or the
    transient-retry cap exhausted against it) — re-running once on the role's
    configured FALLBACK endpoint can genuinely help, so
    run_role_session_with_fallback_async honors `fallback_eligible`.
    OUTPUT-class failures (session completed but structured output missing/
    invalid/unparseable) stay UNMARKED: a different endpoint doesn't fix a
    parse defect — the fix is a same-endpoint reroll (pipeline.
    _single_shot_with_retry) — and unmarked-defaults-to-not-eligible means an
    unclassified error can never silently buy paid cloud time (final review)."""
    err = error_cls(message)
    err.fallback_eligible = True
    return err


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
    1. endpoint.price_per_mtok configured -> computed from token counts. CACHE
       READS (cache_read_input_tokens — re-reading stable context already cached)
       are billed at the discounted price.cache_read when set, else the input rate.
       CACHE WRITES (cache_creation_input_tokens — first-time caching of new
       context) are billed at the normal price.input — a write seeds the cache for
       later reuse, it is not itself a discounted hit, and providers price it at or
       above the input rate, never below. Root-cause fix 2026-06-30 (ultracode
       audit): the prior version summed read+write into one `cached` figure and
       priced the WHOLE thing at the steep read-discount rate, under-counting spend
       by ~50-120x on cache-write-heavy cycles (which is most cycles, since the
       findings/source digest grows every cycle and rarely byte-matches a prior
       call) — silently weakening the budget breaker's input.
       This is how PAID non-first-party endpoints get real spend.
    2. first-party endpoint (base_url None) -> the CLI's client-side estimate.
    3. otherwise (free local) -> usd 0 per §1, tokens still recorded."""
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    cached = cache_read + cache_write  # combined figure: ledger display only
    if endpoint_cfg.price_per_mtok is not None:
        price = endpoint_cfg.price_per_mtok
        # Cache hits billed at the discounted cache_read rate when the endpoint
        # sets one; otherwise fall back to the input rate so an unpriced endpoint
        # is never under-counted. Cache writes ALWAYS bill at the input rate —
        # there is no discount to apply, and using the read rate here is exactly
        # the bug this fix corrects.
        cache_read_rate = price.cache_read if price.cache_read is not None else price.input
        usd = (
            input_tokens * price.input
            + cache_read * cache_read_rate
            + cache_write * price.input
            + output_tokens * price.output
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

    from claude_agent_sdk import AssistantMessage, CLIConnectionError
    from tenacity import (
        AsyncRetrying,
        RetryError,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )

    wall_ceiling = role_cfg.max_wall_seconds or settings.session.default_max_wall_seconds

    async def _attempt() -> tuple[ResultMessage, dict[str, Any]]:
        started = time.monotonic()
        final: ResultMessage | None = None
        # Provisional entry FIRST (reconciled=False): if this session dies
        # mid-flight or hangs past the wall ceiling, the ledger still shows it
        # started — the local report's "unledgered mid-flight spend" finding.
        provisional_index = ledger.record_provisional(
            LedgerEntry(
                cycle=cycle,
                session_type=session_type,
                model=role_cfg.model,
                endpoint=role_cfg.endpoint,
                input_tokens=0,
                output_tokens=0,
                cached_tokens=0,
                usd=0.0,
                wall_seconds=0.0,
                reconciled=False,
            )
        )
        # Best-effort partial usage from the stream (dedupe by message_id —
        # parallel tool calls share ids), so a dead session's entry carries
        # the tokens we SAW even though the final accounting never arrived.
        partial: dict[str, dict[str, Any]] = {}

        def _reconcile_partial(wall: float) -> None:
            usage_sum = {
                "input_tokens": sum(int(u.get("input_tokens") or 0) for u in partial.values()),
                "output_tokens": sum(int(u.get("output_tokens") or 0) for u in partial.values()),
                "cache_read_input_tokens": sum(
                    int(u.get("cache_read_input_tokens") or 0) for u in partial.values()
                ),
                "cache_creation_input_tokens": sum(
                    int(u.get("cache_creation_input_tokens") or 0) for u in partial.values()
                ),
            }
            metrics = finalize_metrics(usage_sum, None, endpoint_cfg, wall)
            ledger.reconcile(
                provisional_index,
                LedgerEntry(
                    cycle=cycle,
                    session_type=session_type,
                    model=role_cfg.model,
                    endpoint=role_cfg.endpoint,
                    reconciled=False,  # stays visibly unreconciled: partial truth
                    **metrics,
                ),
            )

        async def _consume() -> None:
            nonlocal final
            async for message in query(prompt=user_prompt, options=options):
                if isinstance(message, AssistantMessage) and message.usage:
                    partial[message.message_id or str(len(partial))] = message.usage
                if isinstance(message, ResultMessage):
                    final = message

        try:
            await asyncio.wait_for(_consume(), timeout=wall_ceiling)
        except asyncio.TimeoutError:
            # The hang-forever failure mode (local report finding #1): a dead
            # CLI transport never yields a result. Cancel kills the consume
            # task (the SDK closes its transport on cancellation), account
            # what we saw, retry fresh under the standard transient cap.
            _reconcile_partial(time.monotonic() - started)
            run.log(
                f"{session_type} (cycle {cycle}): session exceeded wall ceiling "
                f"{wall_ceiling:.0f}s — killed (partial usage ledgered, unreconciled)"
            )
            raise _TransientSpawnFailure(
                f"session exceeded wall ceiling {wall_ceiling:.0f}s"
            )
        except CLIConnectionError as exc:
            _reconcile_partial(time.monotonic() - started)
            raise _TransientSpawnFailure(f"transport: {exc}") from exc
        except ClaudeSDKError as exc:
            _reconcile_partial(time.monotonic() - started)
            raise _transport_error(
                error_cls, f"{session_type} session transport failure: {exc}"
            ) from exc
        except Exception as exc:
            # The SDK raises a BARE Exception (not a ClaudeSDKError) when the
            # CLI returns an error result mid-stream — notably "Failed to
            # provide valid structured output after N attempts". Treat as
            # transient: a fresh session usually resamples to valid output, and
            # this is bounded by retry.attempts + the per-session budget, after
            # which it surfaces as a loud typed error. Never silent, never
            # infinite (§0). asyncio.CancelledError is a BaseException, so it
            # is not swallowed here.
            _reconcile_partial(time.monotonic() - started)
            raise _TransientSpawnFailure(f"CLI error result: {exc}") from exc
        if final is None:
            _reconcile_partial(time.monotonic() - started)
            raise _TransientSpawnFailure("session ended without a result message")
        wall = time.monotonic() - started

        metrics = finalize_metrics(final.usage, final.total_cost_usd, endpoint_cfg, wall)
        # Reconcile the provisional with the session's final accounting —
        # success AND error results carry usage (SDK_NOTES).
        ledger.reconcile(
            provisional_index,
            LedgerEntry(
                cycle=cycle,
                session_type=session_type,
                model=role_cfg.model,
                endpoint=role_cfg.endpoint,
                **metrics,
            ),
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
            # Non-transient error RESULT (auth/validation/model failure against
            # this endpoint) — transport-class: the endpoint refused the session.
            raise _transport_error(error_cls, message)
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
        raise _transport_error(
            error_cls,
            f"{session_type} session failed after {retry_cfg.attempts} attempts "
            f"(transient): {last}",
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


async def run_role_session_with_fallback_async(**kwargs: Any) -> Spawn:
    """Async core of the reliability net (2026-06-25): spawn the role's primary
    endpoint, and on a typed SessionError after the primary exhausts its
    transient-retry cap, re-run the session ONCE on the role's configured fallback
    endpoint/model. A transient provider outage (e.g. the DeepSeek-Pro degradation
    that failed the evaluator + synthesizer mid-validation) then can't block a run
    from finishing. The failed primary's spend is already ledgered; the fallback
    adds its own entry under the fallback endpoint. Logged as a DECISION
    (invariant 8).

    Split out from run_role_session (2026-06-30, ultracode audit) so the pipeline's
    worker/compose single-shot calls can share it: those calls used to invoke
    run_role_session_async directly, bypassing the fallback entirely under the
    DEFAULT worker_pipeline.enabled=true posture — a primary-endpoint outage there
    crashed the whole run instead of degrading, contradicting config.yaml's own
    'driver-called worker/compose only' comment. Per-page reads (reader_subagent,
    inside the worker's read_one loop) intentionally still do NOT route through
    here — a fallback retry per page would multiply read cost across dozens of
    reads/cycle; a single failed read already degrades gracefully on its own
    (logged, the page just contributes no finding)."""
    settings = kwargs["settings"]
    role = kwargs["role"]
    role_cfg = settings.roles[role]
    error_cls = _ERROR_BY_TYPE[kwargs["session_type"]]
    try:
        return await run_role_session_async(**kwargs)
    except error_cls as exc:
        if not getattr(exc, "fallback_eligible", False):
            # OUTPUT-class (structured output missing/invalid/unparseable) or
            # unclassified: the session REACHED the endpoint — a different one
            # doesn't fix a parse defect. Re-raise so the caller's reroll logic
            # (pipeline._single_shot_with_retry) resamples the PRIMARY instead
            # of every flaky-JSON roll silently buying the paid cloud fallback
            # (final review). Unmarked defaults to NOT eligible by design.
            raise
        fallback = settings.endpoints[role_cfg.endpoint].fallback
        if fallback is None:
            raise
        kwargs["run"].log_decision(
            f"{role}: primary endpoint '{role_cfg.endpoint}' failed after retries "
            f"({type(exc).__name__}); falling back to '{fallback.endpoint}'"
            f"/{fallback.model} to keep the run alive."
        )
        fb_role = role_cfg.model_copy(
            update={"endpoint": fallback.endpoint, "model": fallback.model}
        )
        fb_settings = settings.model_copy(
            update={"roles": {**settings.roles, role: fb_role}}
        )
        return await run_role_session_async(**{**kwargs, "settings": fb_settings})


def run_role_session(**kwargs: Any) -> Spawn:
    """Sync wrapper for driver-called session modules (one event loop per
    session; readers inside the worker use the async core directly). Fallback
    logic lives in run_role_session_with_fallback_async (shared with the
    pipeline's worker/compose calls — see that docstring)."""
    return asyncio.run(run_role_session_with_fallback_async(**kwargs))
