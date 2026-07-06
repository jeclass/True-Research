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
    # Per-MTok price for CACHE-HIT input tokens (re-reads of stable context).
    # Providers discount these steeply (DeepSeek ~2% of the miss rate). When unset
    # the ledger falls back to the input rate (conservative — never under-counts an
    # unpriced endpoint). Setting it makes the ledger + budget breaker accurate so
    # deep runs that re-read a large findings digest each cycle aren't over-charged.
    cache_read: float | None = Field(default=None, ge=0)


class FallbackCfg(_Frozen):
    # Where to re-run a driver-called session when this endpoint fails after its
    # transient-retry cap. The fallback endpoint serves a different model, so both
    # are named explicitly.
    endpoint: str
    model: str


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
    # Reliability net (2026-06-25): if a driver-called session on this endpoint
    # fails after retries, re-run it ONCE here. A transient provider outage (e.g.
    # the DeepSeek-Pro degradation that failed the evaluator + synthesizer mid-
    # validation) then can't block a run from finishing. Only fires on failure, so
    # it costs nothing in normal operation. The async readers don't pass through
    # the sync wrapper, so a fallback never multiplies per-read cost.
    fallback: FallbackCfg | None = None


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
    # Serper (Google SERP API) — portable, key-based PRIMARY web provider. When
    # serper_api_key_env names a key present in .env, the general profile prefers
    # Serper (Google's broad index, cheap -> many queries); without it, search
    # falls back to SearXNG -> DDG. This is what lets the engine run anywhere from
    # a clone with the user's own key (no Docker/self-host required).
    serper_api_key_env: str | None = None
    serper_endpoint: str = "https://google.serper.dev/search"
    serper_gl: str = "us"          # Google country bias
    serper_hl: str = "en"          # Google UI language


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
    # Parallel worker fan-out (roadmap): investigate up to N distinct open
    # questions CONCURRENTLY per cycle, merging before the evaluator. A wall-clock
    # win (overlaps search/read/compose latency), NOT a quality win — token volume,
    # not parallelism, drives result quality — so default 1 (sequential, the proven
    # path). Only takes effect in pipeline mode (the agentic worker is sync). Keep
    # small: each question already fans out max_reads concurrent reads, so N*max_
    # reads bounds total in-flight reads against endpoint rate limits.
    parallel_questions: int = Field(ge=1, default=1)
    # Pre-read relevance reranking of search snippets vs the question
    # (FlashRank, CPU). Optional dependency; unavailable => authority-first
    # rules only. Relevance becomes the primary selection sort key.
    rerank: bool = True


class EvaluatorCfg(_Frozen):
    # Context bounds for the PER-CYCLE evaluator (the cheap gate, on the local
    # 32k model). Without these it overflowed at ~13 findings / 136 sources
    # (~30.7k tokens) and 5xx-ed, halting deep runs (root-cause fix 2026-06-15).
    per_cycle_findings_chars: int = Field(ge=1000)  # total findings-text budget
    per_cycle_max_sources: int = Field(ge=1)        # most-credible N shown
    # GENEROUS bounds for the Opus FINAL gate (cost fix 2026-06-25): it reads far
    # more than the per-cycle gate but is no longer fully unbounded — an exhaustive
    # run's 100-finding digest would cost ~$1+/Opus call. These only bite very large
    # runs; default to comfortably above a normal comprehensive run.
    final_findings_chars: int = Field(default=150000, ge=10000)
    final_max_sources: int = Field(default=120, ge=1)


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


class ExhaustiveCfg(_Frozen):
    # The DEEPEST posture — promoted by --exhaustive. Comprehensive's deep bundle
    # PLUS a much higher per-cycle read budget + per-domain cap, so a genuinely
    # vast topic ingests 1000+ pages. Only worth it where breadth itself is the
    # goal (a full-field systematic review); a focused question concludes long
    # before this matters and you pay for marginal sources. Explicit CLI flags win.
    max_cycles: int = Field(ge=1)
    max_wall_hours: float = Field(gt=0)
    max_budget_usd: float = Field(ge=0)
    max_depth: int = Field(ge=0)
    max_questions: int = Field(ge=1)
    seed_target: int = Field(ge=1)
    max_reads: int = Field(ge=1)       # per-cycle read budget (vs 12 default)
    per_domain_cap: int = Field(ge=1)  # reads per authoritative domain (vs 3)


class VerificationCfg(_Frozen):
    # Adversarial verification wave (COMPREHENSIVE_RESEARCH_SPEC §3). Opt-in;
    # --comprehensive turns it on. Off by default — normal runs are unchanged.
    enabled: bool
    max_findings: int = Field(ge=1)         # top-N by confidence (cost bound)
    min_confidence: float = Field(ge=0.0, le=1.0)  # only verify load-bearing
    # Risk-first targeting (roadmap quick win): spend the fixed max_findings
    # verifier budget where adversarial refutation has the most LEVERAGE — the
    # under-corroborated load-bearing claims — instead of always the highest-
    # confidence ones. A claim already cross-validated by several independent
    # sources needs the verifier least; a high-confidence SINGLE-source claim is
    # exactly CLAUDE.md's flagged risk ("two independent origins for every
    # load-bearing claim"). Orders candidates by (fewest sources, then highest
    # confidence). Default on — a strict targeting improvement at the same spend.
    risk_first: bool = True
    # Opt-in spend cut (default 0 = off): skip verifying findings ALREADY backed
    # by >= N sources (well cross-validated -> low refutation value), focusing the
    # verifier on single-/few-source claims. Approximates "independent" by source
    # COUNT — the available signal; pair with risk_first.
    skip_corroborated_min_sources: int = Field(ge=0, default=0)


class WavesCfg(_Frozen):
    # Wave orchestration (COMPREHENSIVE_RESEARCH_SPEC item 4): BREADTH maps the
    # seed tree, then DEPTH deliberately re-investigates the top findings
    # (primary-source insistence + cross-validation) before VERIFY/SYNTHESIZE.
    # Opt-in; --comprehensive turns it on. Off by default — a normal run never
    # consults the wave field and behaves byte-identically.
    enabled: bool
    depth_findings: int = Field(ge=1)  # top-N findings deepened when breadth concludes
    # Per-question early-stopping (roadmap quick win): skip re-deepening a lead
    # already cross-validated by >= N sources, so the DEPTH budget hardens the
    # under-corroborated leads that actually need it instead of re-confirming
    # settled ones. Unlike VerificationCfg.skip_corroborated_min_sources above
    # (count-only), this field's skip is ENGINE-ENFORCED to also require the
    # N sources span >= 2 distinct hostnames (see depth.py's
    # _independently_corroborated §3.4) — N same-domain sources are not
    # independent corroboration. Default 0 = off (deepen the top-N regardless,
    # as before).
    skip_corroborated_min_sources: int = Field(ge=0, default=0)


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
    # Consecutive worker cycles where EVERY selected read failed to fetch before
    # the driver trips a clean "read_outage" finish — a volume/reader-endpoint
    # outage (e.g. DeepSeek down) churning budget at zero findings, distinct from
    # the hash-stall (which a soft-block's state delta defeats). >1 so a transient
    # blip doesn't trip it (audit #20).
    max_read_outage_cycles: int = Field(ge=1, default=3)
    # Opus final-gate firings allowed per run; the dominant variable cost in
    # the budget posture. After this many, the run accepts the local
    # evaluator's pass (logged) rather than summoning Opus again.
    max_final_evaluations: int = Field(ge=1)
    profiles: list[str] = Field(min_length=1)
    default_profile: str
    # Emit REPORT.pdf next to REPORT.md (markdown -> pure-Python xhtml2pdf, no
    # system libraries so it runs anywhere). A missing dep or render error degrades
    # to a logged decision — it never crashes a finished run.
    emit_pdf: bool = True
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
    # Optional (unlike comprehensive): a config without an `exhaustive:` block still
    # validates — it just can't use --exhaustive (which raises a clean ConfigError).
    # Keeps minimal/test configs and user forks working without forcing the block.
    exhaustive: ExhaustiveCfg | None = None
    verification: VerificationCfg
    waves: WavesCfg
    stub: StubCfg
    # auth_env name -> secret value, from .env (and os.environ as fallback so
    # CI can inject keys). Never printed: SecretStr redacts in repr/str.
    secrets: dict[str, SecretStr] = Field(default_factory=dict, repr=False)

    # Known lens names — kept here (not imported from src.lenses) so settings
    # has no dependency on the lens package. Keep in sync when adding a lens.
    _KNOWN_LENSES: ClassVar[frozenset[str]] = frozenset({"community"})
    # Roles the driver loop ALWAYS invokes, regardless of profile/preset/flags.
    # (final_evaluator/verifier/compose/reader_subagent are conditional — the
    # driver guards on their presence — so they are NOT required here.) Validated
    # at config LOAD so a base-config omission fails loudly up front, not lazily
    # on the role() lookup mid-run (ultracode audit #11, 2026-06-30).
    _REQUIRED_ROLES: ClassVar[frozenset[str]] = frozenset(
        {"initializer", "worker", "evaluator", "synthesizer"}
    )

    @model_validator(mode="after")
    def _cross_check(self) -> "Settings":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile {self.default_profile!r} not in profiles {self.profiles}"
            )
        missing = self._REQUIRED_ROLES - set(self.roles)
        if missing:
            raise ValueError(
                f"config is missing always-required role(s) {sorted(missing)} "
                f"(have: {sorted(self.roles)})"
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
        for ep_name, ep in self.endpoints.items():
            if ep.fallback is not None and ep.fallback.endpoint not in self.endpoints:
                raise ValueError(
                    f"endpoint {ep_name!r} fallback references unknown endpoint "
                    f"{ep.fallback.endpoint!r} (known: {sorted(self.endpoints)})"
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

    # --exhaustive: the DEEPEST posture — the comprehensive bundle PLUS the read
    # dials (per-cycle read budget + per-domain cap) so a vast topic ingests 1000+
    # pages. Promoted the same way (before the generic override loop, so explicit
    # CLI flags still win). Verification + waves on, like comprehensive.
    if overrides.pop("exhaustive", False):
        exh = raw.get("exhaustive")
        if not isinstance(exh, dict):
            raise ConfigError("--exhaustive requires an `exhaustive:` config block")
        for key in ("max_cycles", "max_wall_hours", "max_budget_usd"):
            if key in exh:
                raw[key] = exh[key]
        qt = raw.setdefault("question_tree", {})
        for key in ("max_depth", "max_questions", "seed_target"):
            if key in exh:
                qt[key] = exh[key]
        wp = raw.setdefault("worker_pipeline", {})
        for key in ("max_reads", "per_domain_cap"):
            if key in exh:
                wp[key] = exh[key]
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
                # A preset may only REPLACE a role the base `roles:` block already
                # defines — never invent a new one. Without this, a typo'd role key
                # (e.g. `intializer:`) silently splices in a dead, never-consumed
                # role entry while the role actually meant to be overridden keeps
                # its base (often far pricier) routing — silent narrowing, which
                # CLAUDE.md §3 invariant 8 forbids (ultracode audit #8, 2026-06-30).
                if role not in raw.get("roles", {}):
                    raise ConfigError(
                        f"--{flag_name} preset overrides unknown role {role!r} "
                        f"(known: {sorted(raw.get('roles', {}))}) — likely a typo in "
                        f"config.yaml's `{block_name}.roles`"
                    )
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
            if role not in raw.get("roles", {}):
                raise ConfigError(
                    f"--volume {volume_choice} overrides unknown role {role!r} "
                    f"(known: {sorted(raw.get('roles', {}))}) — likely a typo in "
                    f"config.yaml's `volume_options.{volume_choice}`"
                )
            raw["roles"][role] = cfg

    for key, value in overrides.items():
        if value is not None:
            raw[key] = value

    # dotenv_values reads the file without mutating os.environ (by design —
    # see docs/DECISIONS.md). os.environ is a fallback per auth_env name only.
    env_file_values = {
        k: v for k, v in dotenv_values(str(env_path)).items() if v is not None
    }
    secret_env_names = {
        ep.get("auth_env")
        for ep in raw.get("endpoints", {}).values()
        if isinstance(ep, dict) and ep.get("auth_env")
    }
    # Search-provider API keys (e.g. SERPER_API_KEY) are secrets too — named in the
    # search config rather than an endpoint, so load them the same way. Config-named
    # (not hardcoded) so a fork can point at any key env without touching code.
    _search_raw = raw.get("search", {})
    if isinstance(_search_raw, dict) and _search_raw.get("serper_api_key_env"):
        secret_env_names.add(_search_raw["serper_api_key_env"])
    secrets: dict[str, SecretStr] = {}
    for name in sorted(filter(None, secret_env_names)):
        value = env_file_values.get(name) or os.environ.get(name)
        if value:
            secrets[name] = SecretStr(value)
    raw["secrets"] = secrets

    try:
        return Settings.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration:\n{exc}") from exc
