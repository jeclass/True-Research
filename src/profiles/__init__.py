"""Research profiles (CLAUDE.md §7): swappable tool sets + rubrics + worker
guidance per domain. Adding a domain = adding one Profile; the loop, state,
and invariants never change."""

from __future__ import annotations

from src.errors import ConfigError
from src.profiles.base import Profile, WorkerToolContext, WorkerToolset


def get_profile(name: str) -> Profile:
    from src.profiles.general import GeneralProfile
    from src.profiles.legal import LegalProfile
    from src.profiles.scientific import ScientificProfile
    from src.profiles.visual import VisualProfile

    registry: dict[str, type[Profile]] = {
        GeneralProfile.name: GeneralProfile,
        ScientificProfile.name: ScientificProfile,
        VisualProfile.name: VisualProfile,
        LegalProfile.name: LegalProfile,  # FUTURE DOMAIN — v1 scaffold
    }
    profile_cls = registry.get(name)
    if profile_cls is None:
        raise ConfigError(
            f"profile {name!r} has no implementation (available: {sorted(registry)})"
        )
    return profile_cls()


__all__ = ["Profile", "WorkerToolContext", "WorkerToolset", "get_profile"]
