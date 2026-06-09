"""Cost + token accounting (CLAUDE.md §2, §4). Append-only; every entry records
the endpoint that produced it. The driver reads spend_usd for the global budget
breaker — the SDK keeps no cross-session total, so this ledger is the source of
truth for a run's spend (docs/SDK_NOTES.md)."""

from __future__ import annotations

from src import state
from src.runspace import LEDGER_FILE, Runspace
from src.state import LedgerEntry, LedgerFile


class Ledger:
    def __init__(self, run: Runspace) -> None:
        self._run = run
        path = run.root / LEDGER_FILE
        if path.is_file():
            self._entries = state.parse_ledger(
                path.read_text(encoding="utf-8"), label=str(path)
            ).root
        else:
            self._entries = []

    @property
    def entries(self) -> list[LedgerEntry]:
        return list(self._entries)

    @property
    def spend_usd(self) -> float:
        return sum(entry.usd for entry in self._entries)

    def record(self, entry: LedgerEntry) -> None:
        """Append and persist immediately — a crash right after a session must
        not lose the spend it caused."""
        self._entries.append(entry)
        self.checkpoint()

    def checkpoint(self) -> None:
        self._run.write_text(LEDGER_FILE, state.dump_ledger(LedgerFile(self._entries)))
