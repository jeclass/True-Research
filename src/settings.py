"""Frozen Settings loaded from config.yaml + .env (CLAUDE.md §1).

Secrets are read from .env with dotenv_values — they are NEVER exported into
this process's os.environ. sessions/base.py injects them per spawned session
via ClaudeAgentOptions.env (see docs/SDK_NOTES.md, "Per-session backend env
injection").
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from src.errors import ConfigError

SessionType = Literal["initializer", "worker", "evaluator", "synthesizer"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EndpointCfg(_Frozen):
    base_url: str | None = None
    auth_env: str


class RoleCfg(_Frozen):
    endpoint: str
    model: str
    max_turns: int = Field(ge=1)


class SessionCfg(_Frozen):
    backend: Literal["stub", "sdk"]
    max_budget_usd_per_session: float = Field(ge=0)


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
    profiles: list[str] = Field(min_length=1)
    default_profile: str
    endpoints: dict[str, EndpointCfg] = Field(min_length=1)
    roles: dict[str, RoleCfg] = Field(min_length=1)
    session: SessionCfg
    stub: StubCfg
    # auth_env name -> secret value, from .env (and os.environ as fallback so
    # CI can inject keys). Never printed: SecretStr redacts in repr/str.
    secrets: dict[str, SecretStr] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def _cross_check(self) -> "Settings":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile {self.default_profile!r} not in profiles {self.profiles}"
            )
        for name, role in self.roles.items():
            if role.endpoint not in self.endpoints:
                raise ValueError(
                    f"role {name!r} references unknown endpoint {role.endpoint!r} "
                    f"(known: {sorted(self.endpoints)})"
                )
        return self

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

    for key, value in (overrides or {}).items():
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
