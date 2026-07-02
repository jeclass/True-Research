"""Pydantic schemas for every run-state file (CLAUDE.md §4) plus strict
load/parse helpers. Validation happens on every load AND save — a malformed
file is a loud StateError, never a quiet default."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from src.errors import StateError
from src.settings import SessionType

QuestionStatus = Literal["open", "in_progress", "resolved"]
# "stall" = invariant-5 hash-stall (consecutive no-delta cycles; stall_count > 0).
# "exhausted" = every open question was resolved but the evaluator never produced
# a passing verdict — a DIFFERENT stop condition that used to also be reported as
# "stall" with stall_count=0, making run.json alone ambiguous (audit #19).
FinishReason = Literal[
    "conclusive", "budget", "time", "max_cycles", "stall", "exhausted", "read_outage"
]

_FRONT_MATTER_SEP = "---"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- open_questions.yaml -----------------------------------------------------


class OpenQuestion(_Strict):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    status: QuestionStatus = "open"
    priority: int = Field(ge=1, le=5)
    parent_id: str | None = None
    # §4 lists initializer|evaluator, but §6 has workers spawning child
    # questions on fragmentation — "worker" added to keep both sections true.
    # "depth" tags a question the driver seeds in the DEPTH wave (wave
    # orchestration, COMPREHENSIVE_RESEARCH_SPEC item 4): a deliberate
    # re-investigation of a top finding, not a gap the evaluator found.
    created_by: Literal["initializer", "evaluator", "worker", "depth"]
    resolved_by_finding: str | None = None
    # Evidence track (lens axis, orthogonal to the domain profile). "factual"
    # is the default and the only track a normal run produces; "community"
    # questions route to community search providers and their findings are
    # quarantined into a separate report section (docs/COMMUNITY_LENS_SPEC.md).
    track: Literal["factual", "community"] = "factual"
    # Worker sessions that ended BLOCKED on this question (no usable sources).
    # Gates the evaluator's exhausted-scope close of SEED questions (observed
    # 2026-06-10: an unanswerable seed facet + absolute seed protection ground
    # runs into partial finishes instead of converging).
    blocked_count: int = Field(ge=0, default=0)
    # Question-tree depth: initializer/evaluator seeds are 0; a fragmentation
    # child is parent.depth + 1. Bounds recursive decomposition for deep
    # ("comprehensive") runs (docs/COMPREHENSIVE_RESEARCH_SPEC.md item 2).
    depth: int = Field(ge=0, default=0)


class QuestionList(RootModel[list[OpenQuestion]]):
    def open_items(self) -> list[OpenQuestion]:
        return [q for q in self.root if q.status == "open"]

    def in_progress_items(self) -> list[OpenQuestion]:
        return [q for q in self.root if q.status == "in_progress"]

    def get(self, question_id: str) -> OpenQuestion:
        for q in self.root:
            if q.id == question_id:
                return q
        raise StateError(f"unknown question id {question_id!r}")


# --- sources.json -------------------------------------------------------------


class SourceRecord(_Strict):
    url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: Literal["web", "paper", "page_capture"]
    credibility: int = Field(ge=0, le=100)
    retrieved_at: datetime
    notes: str = ""
    # Span-level citation anchors (roadmap): verbatim quotes pulled from the page
    # text by the reader that most directly support the facts cited from this
    # source — so a report citation points at checkable evidence, not just a URL.
    # Engine-verified substrings only (see reader._verify_quotes); empty for older
    # registries / sources the agentic worker registered without proposing any.
    # First-capture wins, same as the rest of the record (merge_sources never
    # updates an already-registered same-id+same-url source).
    excerpts: list[str] = Field(default_factory=list)


class SourceRegistry(RootModel[dict[str, SourceRecord]]):
    pass


# --- findings/<slug>.md (front-matter + prose) --------------------------------


class FindingMeta(_Strict):
    question_id: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)  # invariant 3: no sourceless findings
    confidence: float = Field(ge=0.0, le=1.0)
    # Inherited from the answered question; quarantines community findings out
    # of the factual synthesis (docs/COMMUNITY_LENS_SPEC.md). Defaulted so
    # every existing finding file loads unchanged.
    track: Literal["factual", "community"] = "factual"
    # Adversarial verification (docs/COMMUNITY_LENS_SPEC sibling: COMPREHENSIVE
    # item 3). An independent session tries to REFUTE the finding's claim:
    # verified = survived; refuted = contradicted (synthesizer demotes it);
    # unverified = not checked (default — normal runs don't verify).
    verification_status: Literal["unverified", "verified", "refuted"] = "unverified"
    verification_note: str = ""


# --- ledger.json ---------------------------------------------------------------


class LedgerEntry(_Strict):
    cycle: int = Field(ge=0)
    session_type: SessionType
    model: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_tokens: int = Field(ge=0)
    usd: float = Field(ge=0)
    wall_seconds: float = Field(ge=0)
    # False => the session started but never returned a ResultMessage (died
    # mid-flight / timed out). Token counts are then best-effort partials from
    # the stream; first-party billed spend may be under-counted (bounded by
    # the per-session budget + wall ceiling). Loud, not silent.
    reconciled: bool = True


class LedgerFile(RootModel[list[LedgerEntry]]):
    pass


# --- verdicts/cycle-<n>.md ------------------------------------------------------


class Verdict(_Strict):
    passed: bool
    unmet_criteria: list[str]
    contradictions: list[str]
    new_questions: list[str]
    notes: str = ""


# --- run.json (run metadata: resume/breaker bookkeeping) -------------------------


class RunMeta(_Strict):
    run_id: str
    question: str
    profile: str
    created_at: datetime
    status: Literal["running", "finished"] = "running"
    finish_reason: FinishReason | None = None
    last_cycle: int = Field(ge=0, default=0)
    stall_count: int = Field(ge=0, default=0)
    active_seconds: float = Field(ge=0, default=0.0)
    final_eval_count: int = Field(ge=0, default=0)
    # Consecutive worker cycles where EVERY selected URL failed to fetch (the
    # volume/reader endpoint is down, not the web) — distinct from "fetched but
    # judged unhelpful". The driver trips a clean circuit breaker once this hits
    # settings.max_read_outage_cycles, instead of churning budget at zero findings
    # through soft-blocks (audit #20). Default 0 keeps old runs schema-compatible.
    read_outage_streak: int = Field(ge=0, default=0)
    # Wave orchestration (COMPREHENSIVE_RESEARCH_SPEC item 4): the current phase
    # of a wave run. "breadth" maps the seed tree; "depth" re-investigates top
    # findings. Persisted so an 8-hour run resumes into the correct wave.
    # Default "breadth" keeps non-wave runs schema-compatible + behaviorally
    # unchanged (the driver only consults it when settings.waves.enabled).
    wave: Literal["breadth", "depth"] = "breadth"


# --- (de)serialization helpers ---------------------------------------------------


def _validation_error(path_label: str, exc: Exception) -> StateError:
    return StateError(f"{path_label} failed validation:\n{exc}")


def parse_questions(text: str, label: str = "open_questions.yaml") -> QuestionList:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _validation_error(label, exc) from exc
    if data is None:
        data = []
    try:
        return QuestionList.model_validate(data)
    except ValidationError as exc:
        raise _validation_error(label, exc) from exc


def dump_questions(questions: QuestionList) -> str:
    return yaml.safe_dump(
        questions.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    )


def parse_sources(text: str, label: str = "sources.json") -> SourceRegistry:
    try:
        return SourceRegistry.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise _validation_error(label, exc) from exc


def dump_sources(sources: SourceRegistry) -> str:
    return json.dumps(sources.model_dump(mode="json"), indent=2, sort_keys=True)


def parse_ledger(text: str, label: str = "ledger.json") -> LedgerFile:
    try:
        return LedgerFile.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise _validation_error(label, exc) from exc


def dump_ledger(ledger: LedgerFile) -> str:
    return json.dumps(ledger.model_dump(mode="json"), indent=2)


def parse_run_meta(text: str, label: str = "run.json") -> RunMeta:
    try:
        return RunMeta.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise _validation_error(label, exc) from exc


def dump_run_meta(meta: RunMeta) -> str:
    return json.dumps(meta.model_dump(mode="json"), indent=2)


def _split_front_matter(text: str, label: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_SEP:
        raise StateError(f"{label}: missing '---' front-matter header")
    try:
        end = next(
            i for i, line in enumerate(lines[1:], start=1)
            if line.strip() == _FRONT_MATTER_SEP
        )
    except StopIteration:
        raise StateError(f"{label}: unterminated front-matter block") from None
    try:
        meta = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise _validation_error(label, exc) from exc
    if not isinstance(meta, dict):
        raise StateError(f"{label}: front-matter must be a YAML mapping")
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return meta, body


def parse_finding(text: str, label: str) -> tuple[FindingMeta, str]:
    meta, body = _split_front_matter(text, label)
    try:
        return FindingMeta.model_validate(meta), body
    except ValidationError as exc:
        raise _validation_error(label, exc) from exc


def dump_finding(meta: FindingMeta, body: str) -> str:
    front = yaml.safe_dump(meta.model_dump(mode="json"), sort_keys=False).strip()
    return f"{_FRONT_MATTER_SEP}\n{front}\n{_FRONT_MATTER_SEP}\n\n{body.strip()}\n"


def parse_verdict(text: str, label: str) -> Verdict:
    meta, body = _split_front_matter(text, label)
    meta["notes"] = body.strip()
    try:
        return Verdict.model_validate(meta)
    except ValidationError as exc:
        raise _validation_error(label, exc) from exc


def dump_verdict(verdict: Verdict) -> str:
    payload = verdict.model_dump(mode="json")
    notes = payload.pop("notes")
    front = yaml.safe_dump(payload, sort_keys=False).strip()
    return f"{_FRONT_MATTER_SEP}\n{front}\n{_FRONT_MATTER_SEP}\n\n{notes.strip()}\n"
