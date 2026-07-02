"""Distill API — one-shot pre-launch call that sharpens a long pasted brief
into a single research question the operator confirms BEFORE any run spends.

webui-only by design (spec 2026-07-01): no Runspace, no ledger (no run
exists yet; a Haiku single-shot costs ~$0.001), and the model/endpoint are
code-defaulted here — NOT a `roles:` entry, so preset/role-override
machinery never touches it. Amnesia posture matches engine sessions:
setting_sources=[], explicit system prompt, no tools, wall timeout.

SECURITY: the paste is the operator's own text — it is DATA to the model
(no tools are exposed, so it cannot redirect anything). The Anthropic key is
read with the same precedence as settings.py (.env then os.environ) and
never appears in any response, error detail, or log line; failures return a
GENERIC 502 (no exception text — it could quote the paste or the endpoint).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import dotenv_values
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

DISTILL_MODEL = "claude-haiku-4-5-20251001"
DISTILL_MAX_WALL_SECONDS = 60
_MAX_TEXT_CHARS = 200_000

_SYSTEM_PROMPT = """\
You sharpen a pasted brief into a research assignment for an autonomous,
multi-hour research engine. The user pasted TEXT that may be a question,
notes, an article, or a rambling brief.

Return:
1. research_question — the ONE research question the text is really asking,
   phrased so the engine can investigate it through web research. Preserve
   every constraint the text states (population, timeframe, geography,
   budget, dose, product, jurisdiction...).
2. context_summary — 1-3 sentences of background from the text that a
   researcher needs (why they're asking, constraints that shape a good
   answer).

Do NOT answer the question. Do NOT invent constraints the text doesn't
state. You have NO tools. Respond ONLY via the enforced JSON schema."""


class DistillRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    text: str

    @field_validator("text")
    @classmethod
    def _text_sane(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        if len(v) > _MAX_TEXT_CHARS:
            raise ValueError(f"text exceeds {_MAX_TEXT_CHARS} characters")
        return v


class DistillOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_question: str
    context_summary: str


async def _query_structured(text: str, api_key: str) -> DistillOutput:
    """SDK seam (monkeypatched in tests): ONE fresh amnesiac session, API-side
    structured output, killed at the wall ceiling."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        model=DISTILL_MODEL,
        system_prompt=_SYSTEM_PROMPT,
        tools=[],
        allowed_tools=[],
        permission_mode="dontAsk",
        max_turns=2,
        env={"ANTHROPIC_API_KEY": api_key},
        setting_sources=[],
        output_format={"type": "json_schema", "schema": DistillOutput.model_json_schema()},
    )
    final: ResultMessage | None = None

    async def _consume() -> None:
        nonlocal final
        async for message in query(prompt=text, options=options):
            if isinstance(message, ResultMessage):
                final = message

    await asyncio.wait_for(_consume(), timeout=DISTILL_MAX_WALL_SECONDS)
    if (
        final is None
        or final.is_error
        or final.subtype != "success"
        or final.structured_output is None
    ):
        raise RuntimeError("distill session did not return structured output")
    return DistillOutput.model_validate(final.structured_output)


async def distill(req: DistillRequest, env_path: Path) -> dict:
    api_key = dotenv_values(str(env_path)).get("ANTHROPIC_API_KEY") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )
    if not api_key:
        raise HTTPException(status_code=409, detail="ANTHROPIC_API_KEY not set")
    try:
        out = await _query_structured(req.text, api_key)
    except HTTPException:
        raise
    except Exception:
        # Generic on purpose: exception text could quote the paste/endpoint.
        raise HTTPException(status_code=502, detail="distill failed")
    return {
        "research_question": out.research_question,
        "context_summary": out.context_summary,
    }
