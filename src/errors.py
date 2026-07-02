"""Typed errors shared across the engine. No bare except anywhere; every
failure surfaces as one of these or propagates untouched."""


class EngineError(Exception):
    """Base for all engine errors."""


class ConfigError(EngineError):
    """config.yaml / .env is invalid or missing something required."""


class StateError(EngineError):
    """A run-state file failed validation or (de)serialization."""


class RunspaceError(EngineError):
    """Run directory problems: missing run, finished run, lock conflicts."""
