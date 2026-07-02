"""Cost + token accounting (CLAUDE.md §2, §4). Append-only; every entry records
the endpoint that produced it. The driver reads spend_usd for the global budget
breaker — the SDK keeps no cross-session total, so this ledger is the source of
truth for a run's spend (docs/SDK_NOTES.md)."""

from __future__ import annotations

from src import state
from src.runspace import LEDGER_FILE, Runspace
from src.state import LedgerEntry, LedgerFile


class Ledger:
    def __init__(self, run: Runspace, filename: str = LEDGER_FILE) -> None:
        self._run = run
        self._filename = filename
        path = run.root / filename
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

    def record_provisional(self, entry: LedgerEntry) -> int:
        """Append a provisional (reconciled=False) entry at session start and
        return its index. A session that dies mid-flight leaves this entry
        behind as visible evidence of unledgered billed spend."""
        self._entries.append(entry)
        self.checkpoint()
        return len(self._entries) - 1

    def reconcile(self, index: int, entry: LedgerEntry) -> None:
        """Replace a provisional entry with the session's final accounting."""
        self._entries[index] = entry
        self.checkpoint()

    @property
    def unreconciled_count(self) -> int:
        return sum(1 for e in self._entries if not e.reconciled)

    def checkpoint(self) -> None:
        self._run.write_text(self._filename, state.dump_ledger(LedgerFile(self._entries)))
