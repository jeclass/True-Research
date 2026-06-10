"""Custom tool / MCP wiring (CLAUDE.md §2, Phase 4). In-process MCP servers
the profiles attach to worker sessions. Connector fetches are engine-side
httpx; failures surface as tool error results, never fabricated content."""

from src.errors import EngineError


class ConnectorError(EngineError):
    """A profile connector (academic API, search fallback, page capture)
    failed: unreachable endpoint, missing dependency, bad payload."""
