"""Frozen Settings loaded from config.yaml + .env (CLAUDE.md §1).

Secrets are read from .env with dotenv_values — they are NEVER exported into
this process's os.environ. sessions/base.py injects them per spawned session
via ClaudeAgentOptions.env (see docs/SDK_NOTES.md, "Per-session backend env
injection").
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from src.errors import ConfigError

SessionType = Literal[
    "initializer", "worker", "evaluator", "synthesizer", "reader", "judge"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PriceCfg(_Frozen):
    # USD per million tokens. Set for PAID non-first-party endpoints so the
    # ledger and budget breaker see real spend; omit for free local endpoints.
    input: float = Field(ge=0)
    output: float = Field(ge=0)


class EndpointCfg(_Frozen):
    base_url: str | None = None
    auth_env: str
    price_per_mtok: PriceCfg | None = None
    # Disable extended thinking for this endpoint (volume stages: read/query-gen/
    # compose EXTRACT, they don't reason). DeepSeek Flash defaults to thinking,
    # which balloons read output to ~16k tokens and accumulates across retry
    # turns (observed 2026-06-16: $0.16 outlier reads). Injected as
    # MAX_THINKING_TOKENS=0 per session. Keep thinking ON for judgment endpoints.
    disable_thinking: bool = False


class RoleCfg(_Frozen):
    endpoint: str
    model: str
    max_turns: int = Field(ge=1)
    # Per-session wall ceiling; falls back to session.default_max_wall_seconds.
    # A hung CLI transport must die loudly, never hang the loop (local report
    # finding #1).
    max_wall_seconds: float | None = Field(default=None, gt=0)


class SessionCfg(_Frozen):
    backend: Literal["stub", "sdk"]
    max_budget_usd_per_session: float = Field(ge=0)
    default_max_wall_seconds: float = Field(gt=0)


class ReaderCfg(_Frozen):
    max_page_chars: int = Field(ge=1000)
    max_failures_per_session: int = Field(ge=1)
    fetch_timeout_seconds: float = Field(gt=0)
    require_reads: bool = True
    # One Scrapling stealth-browser retry per failed fetch (bot-walls,
    # JS-only pages). Optional dependency; unavailable => tier 1 only.
    stealth_fallback: bool = True


class RetryCfg(_Frozen):
    # Transient-failure retries (CLAUDE.md §8 Phase 5): transport errors and
    # HTTP 429/5xx/529 only. Permanent failures are never retried.
    attempts: int = Field(ge=1)
    base_delay_seconds: float = Field(gt=0)
    max_delay_seconds: float = Field(gt=0)


class SearchCfg(_Frozen):
    # MCP search fallback for local-routed workers (§1): WebSearch is an
    # Anthropic-hosted tool and does not exist against non-first-party
    # endpoints. A SearXNG instance fills the gap.
    searxng_base_url: str | None = None
    max_results: int = Field(ge=1)


class WorkerPipelineCfg(_Frozen):
    # Pipeline-worker mode (docs/PIPELINE_WORKER_SPEC.md): replaces the
    # open-loop agentic worker with single-shot local calls + engine
    # orchestration — the pattern local models execute flawlessly. The
    # agentic path remains when enabled=false.
    enabled: bool
    queries_per_question: int = Field(ge=1)
    urls_per_query: int = Field(ge=1)
    max_reads: int = Field(ge=1)
    per_domain_cap: int = Field(ge=1)
    # Pre-read relevance reranking of search snippets vs the question
    # (FlashRank, CPU). Optional dependency; unavailable => authority-first
    # rules only. Relevance becomes the primary selection sort key.
    rerank: bool = True


class EvaluatorCfg(_Frozen):
    # Context bounds for the PER-CYCLE evaluator (the cheap gate, on the local
    # 32k model). Without these it overflowed at ~13 findings / 136 sources
    # (~30.7k tokens) and 5xx-ed, halting deep runs (root-cause fix
    # 2026-06-15). The Opus final gate is exempt — it keeps full text.
    per_cycle_findings_chars: int = Field(ge=1000)  # total findings-text budget
    per_cycle_max_sources: int = Field(ge=1)        # most-credible N shown


class QuestionTreeCfg(_Frozen):
    # Bounds on the open-question tree (docs/COMPREHENSIVE_RESEARCH_SPEC item 2).
    # Defaults are PERMISSIVE — they bound runaway recursion/breadth without
    # changing certified-run behavior (~12 questions, depth <=2). The
    # comprehensive bundle below raises them for deep runs.
    max_depth: int = Field(ge=0)        # fragmentation refused past this depth
    max_questions: int = Field(ge=1)    # total questions a run may create
    seed_target: int = Field(ge=1)      # questions the initializer aims for
    # Invariant-5 backstop: a question the worker has BLOCKED on this many times
    # has no reachable sources — the evaluator retires it as a documented
    # limitation so the worker stops re-picking it and the run can converge,
    # instead of looping on an unanswerable question (observed 2026-06-16: a
    # hard 0DTE-options question blocked 12x and starved the backlog).
    retire_blocked_after: int = Field(ge=1)


class ComprehensiveCfg(_Frozen):
    # "Go deep" bundle promoted by --comprehensive. Values live in config (no
    # magic numbers in code); load_settings copies them over the top-level
    # breakers + question_tree when the flag is set. Explicit CLI overrides
    # still win over these.
    max_cycles: int = Field(ge=1)
    max_wall_hours: float = Field(gt=0)
    max_budget_usd: float = Field(ge=0)
    max_depth: int = Field(ge=0)
    max_questions: int = Field(ge=1)
    seed_target: int = Field(ge=1)


class VerificationCfg(_Frozen):
    # Adversarial verification wave (COMPREHENSIVE_RESEARCH_SPEC §3). Opt-in;
    # --comprehensive turns it on. Off by default — normal runs are unchanged.
    enabled: bool
    max_findings: int = Field(ge=1)         # top-N by confidence (cost bound)
    min_confidence: float = Field(ge=0.0, le=1.0)  # only verify load-bearing


class WavesCfg(_Frozen):
    # Wave orchestration (COMPREHENSIVE_RESEARCH_SPEC item 4): BREADTH maps the
    # seed tree, then DEPTH deliberately re-investigates the top findings
    # (primary-source insistence + cross-validation) before VERIFY/SYNTHESIZE.
    # Opt-in; --comprehensive turns it on. Off by default — a normal run never
    # consults the wave field and behaves byte-identically.
    enabled: bool
    depth_findings: int = Field(ge=1)  # top-N findings deepened when breadth concludes


class StubCfg(_Frozen):
    seed_questions: int = Field(ge=1)
    worker_no_delta: bool
    sleep_seconds: float = Field(ge=0)
    cost_usd: float = Field(ge=0)


class Settings(_Frozen):
    runs_dir: str
    max_budget_usd: float = Field(ge=0)
    max_wall_hours: float = Field(gt=0)
    max_cycles: int = Field(ge=1)
    stall_cycles: int = Field(ge=1)
    # Opus final-gate firings allowed per run; the dominant variable cost in
    # the budget posture. After this many, the run accepts the local
    # evaluator's pass (logged) rather than summoning Opus again.
    max_final_evaluations: int = Field(ge=1)
    profiles: list[str] = Field(min_length=1)
    default_profile: str
    # Active evidence lenses (orthogonal to profile; docs/COMMUNITY_LENS_SPEC).
    # Empty by default — a normal run produces only factual-track findings.
    # Validated against the known set here to avoid importing the lens package
    # (which imports Settings).
    lenses: list[str] = Field(default_factory=list)
    endpoints: dict[str, EndpointCfg] = Field(min_length=1)
    roles: dict[str, RoleCfg] = Field(min_length=1)
    session: SessionCfg
    reader: ReaderCfg
    search: SearchCfg
    retry: RetryCfg
    worker_pipeline: WorkerPipelineCfg
    evaluator: EvaluatorCfg
    question_tree: QuestionTreeCfg
    comprehensive: ComprehensiveCfg
    verification: VerificationCfg
    waves: WavesCfg
    stub: StubCfg
    # auth_env name -> secret value, from .env (and os.environ as fallback so
    # CI can inject keys). Never printed: SecretStr redacts in repr/str.
    secrets: dict[str, SecretStr] = Field(default_factory=dict, repr=False)

    # Known lens names — kept here (not imported from src.lenses) so settings
    # has no dependency on the lens package. Keep in sync when adding a lens.
    _KNOWN_LENSES: ClassVar[frozenset[str]] = frozenset({"community"})

    @model_validator(mode="after")
    def _cross_check(self) -> "Settings":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile {self.default_profile!r} not in profiles {self.profiles}"
            )
        for lens in self.lenses:
            if lens not in self._KNOWN_LENSES:
                raise ValueError(
                    f"unknown lens {lens!r} (known: {sorted(self._KNOWN_LENSES)})"
                )
        for name, role in self.roles.items():
            if role.endpoint not in self.endpoints:
                raise ValueError(
                    f"role {name!r} references unknown endpoint {role.endpoint!r} "
                    f"(known: {sorted(self.endpoints)})"
                )
        return self

    def is_full_local(self) -> bool:
        """True when EVERY role routes to a non-first-party endpoint — §1
        requires a loud warning at run start in that posture."""
        return all(
            self.endpoints[role.endpoint].base_url is not None
            for role in self.roles.values()
        )

    def role(self, name: str) -> RoleCfg:
        """Role lookup with a clear error — some roles (vision_reader) are
        only required by specific profiles, so absence is a config error at
        use time, not load time."""
        role = self.roles.get(name)
        if role is None:
            raise ConfigError(
                f"role {name!r} is not configured in config.yaml `roles:` — "
                f"configured roles: {sorted(self.roles)}"
            )
        return role

    def secret_for(self, endpoint_name: str) -> SecretStr:
        """Secret for an endpoint's auth_env. Raises ConfigError if absent —
        callers must not paper over a missing key."""
        endpoint = self.endpoints.get(endpoint_name)
        if endpoint is None:
            raise ConfigError(f"unknown endpoint {endpoint_name!r}")
        value = self.secrets.get(endpoint.auth_env)
        if value is None or not value.get_secret_value():
            raise ConfigError(
                f"endpoint {endpoint_name!r} needs {endpoint.auth_env} in .env "
                "(or the process environment); it is not set"
            )
        return value


def load_settings(
    config_path: str | Path = "config.yaml",
    env_path: str | Path = ".env",
    overrides: dict[str, object] | None = None,
) -> Settings:
    """Build the frozen Settings. `overrides` are explicit CLI values
    (e.g. {"max_cycles": 3}) — None values are ignored."""
    import os

    config_file = Path(config_path)
    if not config_file.is_file():
        raise ConfigError(f"config file not found: {config_file}")
    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file {config_file} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {config_file} must be a YAML mapping")

    overrides = dict(overrides or {})

    # --comprehensive: promote the comprehensive bundle over the top-level
    # breakers + question_tree BEFORE the generic override loop, so explicit
    # CLI flags (--max-budget-usd, etc.) still win over the bundle.
    if overrides.pop("comprehensive", False):
        comp = raw.get("comprehensive")
        if not isinstance(comp, dict):
            raise ConfigError("--comprehensive requires a `comprehensive:` config block")
        for key in ("max_cycles", "max_wall_hours", "max_budget_usd"):
            if key in comp:
                raw[key] = comp[key]
        qt = raw.setdefault("question_tree", {})
        for key in ("max_depth", "max_questions", "seed_target"):
            if key in comp:
                qt[key] = comp[key]
        # Comprehensive runs verify by default (the trust differentiator) and
        # orchestrate waves (BREADTH->DEPTH->VERIFY->SYNTHESIZE, item 4).
        raw.setdefault("verification", {})["enabled"] = True
        raw.setdefault("waves", {})["enabled"] = True

    # --verify: enable the verification wave independent of comprehensive.
    if overrides.pop("verify", False):
        raw.setdefault("verification", {})["enabled"] = True

    # --waves: enable BREADTH->DEPTH orchestration independent of comprehensive
    # (lets a shorter run exercise the depth wave without the deep seed bundle).
    if overrides.pop("waves", False):
        raw.setdefault("waves", {})["enabled"] = True

    # --budget: swap the Opus judgment roles (compose/synthesis/verifier) to
    # cheaper backends + cap verification, to keep a comprehensive run under
    # ~$1 (an explicit cost/quality trade). The `budget:` block is meta-config,
    # consumed here and never seen by Settings — pop it unconditionally.
    def _apply_preset(block_name: str, flag_name: str) -> None:
        # Role-override presets (--budget, --cheap). The block is meta-config,
        # consumed here and never seen by Settings — pop it unconditionally.
        block = raw.pop(block_name, None)
        if overrides.pop(flag_name, False):
            if not isinstance(block, dict):
                raise ConfigError(f"--{flag_name} requires a `{block_name}:` config block")
            for role, cfg in block.get("roles", {}).items():
                raw["roles"][role] = cfg
            if "verification_max_findings" in block:
                raw.setdefault("verification", {})["max_findings"] = block[
                    "verification_max_findings"
                ]
            # A preset may also promote scalar breakers (e.g. --cheap pins a $1
            # hard cap so Config A honors the operator's firm under-$1 rule
            # structurally). Applied before the generic override loop, so an
            # explicit CLI flag (--max-budget-usd) still wins.
            for key in ("max_budget_usd", "max_wall_hours", "max_cycles"):
                if key in block:
                    raw[key] = block[key]

    # Posture presets (architect review 2026-06-16): ONE efficient build (Groq
    # volume + DeepSeek init/verify/synth) at two named points — --cheap = qwen
    # gate + 3 verify passes (~$0.7-1); --accurate = opus gate + 10 passes
    # (~$1-1.5). --budget is the legacy local-volume posture. Last-applied wins.
    _apply_preset("budget", "budget")
    _apply_preset("cheap", "cheap")
    _apply_preset("accurate", "accurate")

    # --gate {qwen,opus} + --verify-depth N: the two posture knobs, DECOUPLED from
    # the presets (architect review). gate-trust (terminal auditor) and verify-
    # depth (grounded refutation passes) are orthogonal, so they override their
    # preset cell independently and win over it. gate_options is meta-config — pop
    # it unconditionally so it never reaches the (extra="forbid") Settings model.
    gate_block = raw.pop("gate_options", None)
    gate_choice = overrides.pop("gate", None)
    if gate_choice is not None:
        if not isinstance(gate_block, dict) or gate_choice not in gate_block:
            raise ConfigError(
                f"--gate {gate_choice} requires a `gate_options.{gate_choice}` config block"
            )
        raw["roles"]["final_evaluator"] = gate_block[gate_choice]

    verify_depth = overrides.pop("verify_depth", None)
    if verify_depth is not None:
        raw.setdefault("verification", {})["max_findings"] = verify_depth

    # --volume {groq,deepseek,local}: swap the 4 high-volume roles to a fallback
    # backend (provider outage / rate-cap) without touching judgment/gate routing.
    # volume_options is meta-config — pop unconditionally (extra="forbid").
    volume_block = raw.pop("volume_options", None)
    volume_choice = overrides.pop("volume", None)
    if volume_choice is not None:
        if not isinstance(volume_block, dict) or volume_choice not in volume_block:
            raise ConfigError(
                f"--volume {volume_choice} requires a `volume_options.{volume_choice}` config block"
            )
        for role, cfg in volume_block[volume_choice].items():
            raw["roles"][role] = cfg

    for key, value in overrides.items():
        if value is not None:
            raw[key] = value

    # dotenv_values reads the file without mutating os.environ (by design —
    # see docs/DECISIONS.md). os.environ is a fallback per auth_env name only.
    env_file_values = {
        k: v for k, v in dotenv_values(str(env_path)).items() if v is not None
    }
    auth_envs = {
        ep.get("auth_env")
        for ep in raw.get("endpoints", {}).values()
        if isinstance(ep, dict) and ep.get("auth_env")
    }
    secrets: dict[str, SecretStr] = {}
    for name in sorted(filter(None, auth_envs)):
        value = env_file_values.get(name) or os.environ.get(name)
        if value:
            secrets[name] = SecretStr(value)
    raw["secrets"] = secrets

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration:\n{exc}") from exc
