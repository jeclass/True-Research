"""Session backends. The driver looks sessions up by role name through
get_backend() and never imports a concrete implementation — cognition stays
swappable (CLAUDE.md §5). Sessions record their own ledger entries (so failed
sessions still account their spend); the driver only checkpoints and reads."""

from __future__ import annotations

from typing import Callable

from src.errors import ConfigError
from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions.base import SessionResult
from src.settings import Settings

SessionFn = Callable[[Runspace, Settings, int, Ledger], SessionResult]
Backend = dict[str, SessionFn]


def get_backend(settings: Settings) -> Backend:
    if settings.session.backend == "stub":
        from src.sessions import stub

        return {
            "initializer": stub.run_initializer,
            "worker": stub.run_worker,
            "evaluator": stub.run_evaluator,
            "synthesizer": stub.run_synthesizer,
        }
    if settings.session.backend == "sdk":
        from src.sessions import evaluator, initializer, synthesizer, worker

        return {
            "initializer": initializer.run,
            "worker": worker.run,
            "evaluator": evaluator.run,
            "synthesizer": synthesizer.run,
        }
    raise ConfigError(f"unknown session backend {settings.session.backend!r}")


__all__ = ["Backend", "SessionFn", "get_backend", "Ledger", "SessionResult"]
