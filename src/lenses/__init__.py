"""Evidence lenses — the second composition axis (docs/COMMUNITY_LENS_SPEC.md).

A *profile* (src/profiles/) is the DOMAIN axis: general / scientific / visual /
(legal, future). Exactly one per run; it sets the source types and the
evaluator rubric. Mutually exclusive.

A *lens* is the ORTHOGONAL evidence axis: zero or more per run, composed on top
of whichever profile is active. A lens contributes (a) its own search channel,
(b) seed questions on a non-factual `track`, and (c) a quarantined report
section. Community is the first lens.

The two axes are perpendicular: `--profile scientific --lens community` asks
"what do the trials say AND what do patients report", with a hard wall between
the two so anecdote can never be cited as fact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from src.errors import ConfigError
from src.settings import Settings


class Lens(ABC):
    name: ClassVar[str]

    @abstractmethod
    def search_providers(self, settings: Settings) -> list[tuple[str, Any]]:
        """(name, async fn(query) -> [{title,url,snippet}]) pairs the pipeline
        queries for this lens's `track` questions instead of the profile's."""

    @abstractmethod
    def seed_questions(self, main_question: str) -> list[tuple[str, int]]:
        """(question, priority) pairs the initializer adds on this lens's track
        when the lens is active. Keep the count small — these run real cycles."""

    @abstractmethod
    def track(self) -> str:
        """The evidence track this lens owns (e.g. 'community')."""

    @abstractmethod
    def report_section_title(self) -> str:
        """Heading for this lens's quarantined section in REPORT.md."""

    @abstractmethod
    def report_section_framing(self) -> str:
        """One paragraph the synthesizer places under the heading, framing the
        section's epistemic status (e.g. sentiment, not verified evidence)."""


_LENSES: dict[str, type[Lens]] = {}


def register(cls: type[Lens]) -> type[Lens]:
    _LENSES[cls.name] = cls
    return cls


def get_lens(name: str) -> Lens:
    try:
        return _LENSES[name]()
    except KeyError:
        raise ConfigError(
            f"unknown lens {name!r}; available: {sorted(_LENSES)}"
        ) from None


def available_lenses() -> list[str]:
    return sorted(_LENSES)


def lens_for_track(track: str, active: list[str]) -> Lens | None:
    """The active lens that owns `track`, or None (factual track has no lens)."""
    for name in active:
        lens = get_lens(name)
        if lens.track() == track:
            return lens
    return None


# Import concrete lenses so registration happens on package import.
from src.lenses import community as _community  # noqa: E402,F401
