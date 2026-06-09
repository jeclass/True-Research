# Claude Agent SDK (Python) — verified facts

Session 0 verification notes for the Marathon Research Engine. Every statement below was
verified on 2026-06-09 against one of two sources, cited inline:

- **[src]** — the installed package source: `claude-agent-sdk 0.2.95` (PyPI), read directly
  from `.venv/lib/python3.11/site-packages/claude_agent_sdk/`.
- **[docs]** — official docs at `code.claude.com/docs/en/agent-sdk/*` and
  `code.claude.com/docs/en/env-vars`, fetched 2026-06-09.

Anything we could **not** verify in this environment is listed at the bottom under
"Explicitly unverified" — nothing in this file is from memory.

## Versions

- `claude-agent-sdk` **0.2.95** [src: `_version.py`]. Requires Python ≥ 3.10 [docs]; we run 3.11.15.
- The wheel **bundles the Claude Code CLI v2.1.170** at `claude_agent_sdk/_bundled/claude`
  (~237 MB) [src: `_cli_version.py`, on-disk check]. CLI resolution order: bundled binary
  first, then `shutil.which("claude")`, then known install paths
  [src: `_internal/transport/subprocess_cli.py:81-112`]. No separate Claude Code install is
  needed. `CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK` skips the version handshake on connect
  [src: `subprocess_cli.py:420`].

## Spawning one fresh session

- `query(prompt=..., options=ClaudeAgentOptions(...)) -> AsyncIterator[Message]` is the
  one-shot, unidirectional primitive: every call spawns a fresh CLI subprocess and a **new
  session with no prior conversation state** (unless `resume`/`continue_conversation` is set)
  [src: `query.py:11-36`; docs python reference]. This is exactly the amnesiac-session
  primitive the engine needs. `ClaudeSDKClient` exists for bidirectional/interactive use —
  not needed for the engine loop.
- Message stream: `SystemMessage(subtype="init")` (carries `session_id`), then
  `AssistantMessage`/`UserMessage`/`StreamEvent`s, terminated by exactly one `ResultMessage`
  [docs cost-tracking; src: `types.py`].
- Typed errors exported by the SDK: `ClaudeSDKError` (base), `CLIConnectionError`,
  `CLINotFoundError`, `ProcessError` (has exit code), `CLIJSONDecodeError`,
  `MessageParseError` [src: `_errors.py`]. Our session wrapper maps these to the engine's
  typed errors.

## `ClaudeAgentOptions` surface (the fields we care about)

All from [src: `types.py:1579-1930`], CLI flag mapping from [src: `subprocess_cli.py:221-410`].

| Option | Semantics (verified) |
|---|---|
| `model` | `--model`. Any model alias/ID string; passed through to the CLI. |
| `fallback_model` | `--fallback-model`, used if primary fails. |
| `system_prompt` | `None` → CLI gets `--system-prompt ""` (**empty prompt, not the Claude Code preset**). `str` → custom prompt. `{"type":"preset","preset":"claude_code"}` → CLI default prompt. Engine sessions always pass an explicit string. |
| `tools` | Base set of built-in tools. `[]` disables all built-ins; list of names selects; preset `claude_code` = default set. |
| `allowed_tools` / `disallowed_tools` | Auto-approve / hard-remove specific tools (`--allowedTools` / `--disallowedTools`). |
| `permission_mode` | `default` / `acceptEdits` / `bypassPermissions` / `plan` / `dontAsk`. |
| `max_turns` | `--max-turns`. **Unset = unlimited** — the engine must always set it (CLAUDE.md invariant 4 confirmed necessary). |
| `max_budget_usd` | `--max-budget-usd`. **Native per-session budget breaker**: query stops with result subtype `error_max_budget_usd` when exceeded. Engine gets a per-session breaker for free, on top of the driver's global one. |
| `cwd` | Working directory of the spawned session. Engine points this at `runs/<id>/`. |
| `env` | **Per-subprocess env injection.** See next section. |
| `setting_sources` | `None` (default) → no `--setting-sources` flag → **CLI default behavior, which loads user+project+local filesystem settings (and CLAUDE.md via "project")**. `[]` → full isolation. Engine sessions must pass `[]` explicitly or amnesia (invariant 1) is violated by `~/.claude` and repo `CLAUDE.md` leaking in. |
| `agents` | `dict[str, AgentDefinition]` — programmatic subagents, sent via initialize request. `AgentDefinition` has `description`, `prompt`, `tools`, `model` (alias `"sonnet"/"opus"/"haiku"/"inherit"` **or full model ID**), `maxTurns`, `effort`, `permissionMode` [src: `types.py:83-101`]. |
| `mcp_servers` | dict → `--mcp-config '{"mcpServers": ...}'` JSON; `strict_mcp_config` ignores all other MCP config sources. |
| `output_format` | `{"type":"json_schema","schema":{...}}` → `--json-schema`; the parsed result arrives in `ResultMessage.structured_output`. Useful for evaluator verdicts in Phase 2. |
| `thinking` / `effort` | `--thinking adaptive|disabled` (or `--max-thinking-tokens N` for the legacy enabled form); `--effort low|medium|high|xhigh|max`. |
| `include_partial_messages` | Streams `StreamEvent`s for live progress display. |
| `extra_args` | Escape hatch for any CLI flag. |
| `stderr` | Callback receiving CLI stderr lines (debug logging). |

## Per-session token usage and cost

- `ResultMessage` fields [src: `types.py:1145-1167`]: `total_cost_usd`, `usage` (aggregate
  `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`),
  `model_usage` (**per-model breakdown**: `inputTokens`, `outputTokens`,
  `cacheReadInputTokens`, `cacheCreationInputTokens`, `webSearchRequests`, `costUSD`, ...),
  `num_turns`, `duration_ms`, `duration_api_ms`, `session_id`, `is_error`, `subtype`,
  `api_error_status` (HTTP status of a failing API call, CLI ≥ 2.1.110), `permission_denials`,
  `structured_output`.
- **Both success and error results carry `usage`/`total_cost_usd`** — a failed session still
  spent tokens; the ledger must record it either way [docs cost-tracking].
- **`total_cost_usd` is a client-side estimate** computed from a price table bundled into the
  CLI — not authoritative billing. Fine for circuit breakers and run reporting; do not treat
  ledger totals as invoices [docs cost-tracking, explicit warning].
- The SDK keeps **no cross-call total**; each `query()` reports only itself. The engine's
  `Ledger` accumulates across sessions (this is by design in CLAUDE.md).
- If per-step usage is ever summed from `AssistantMessage.usage`: parallel tool calls emit
  multiple assistant messages **sharing one `message_id` with identical usage — dedupe by id**
  [docs cost-tracking]. The engine reads the `ResultMessage` aggregate instead, which avoids
  this entirely.
- Prompt caching is **automatic** in the Agent SDK — nothing to switch on. The lever we
  control is prompt-prefix stability (and optionally `ENABLE_PROMPT_CACHING_1H=1` via
  `options.env` for a 1-hour TTL at a higher write rate) [docs cost-tracking].

## Per-session backend env injection (the load-bearing fact for §1)

- The subprocess transport builds the child env as
  `{**os.environ (minus CLAUDECODE), "CLAUDE_CODE_ENTRYPOINT": "sdk-py", **options.env}` —
  **`options.env` always wins, and nothing touches the parent process env**
  [src: `subprocess_cli.py:425-460`]. Injection is genuinely per spawned session.
- The Claude Code CLI honors, from its environment [docs env-vars]:
  - `ANTHROPIC_API_KEY` — sent as `X-Api-Key`; **overrides subscription login when set**.
  - `ANTHROPIC_AUTH_TOKEN` — custom `Authorization: Bearer <value>` header.
  - `ANTHROPIC_BASE_URL` — overrides the API endpoint (proxy/gateway/local server).
  - Also useful: `ANTHROPIC_CUSTOM_HEADERS`, `API_TIMEOUT_MS` (default 600000),
    `CLAUDE_CODE_MAX_RETRIES`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.
- Consequence for `sessions/base.py`: build the env dict per endpoint
  (`{"ANTHROPIC_BASE_URL": ..., "<auth_env>": <secret>}`) and pass it via `options.env`.
  **The driver must keep secrets out of its own `os.environ`** — child processes inherit the
  parent env, and `options.env` can only override keys, not remove them. Loading `.env` into
  a Settings object (not `os.environ`) makes cross-endpoint leakage structurally impossible.
- **Subagent constraint:** `AgentDefinition.model` can route a subagent to a different
  *model*, but subagents run inside the same CLI subprocess and therefore share the parent
  session's env → **endpoint (base_url/auth) mixing is per-session, not per-subagent**.
  Hybrid routing (CLAUDE.md §1) holds at session granularity; a "local reader_subagent" in
  Phase 4 means either the whole worker session targets local, or readers are spawned as
  separate sessions.

## Ollama local backend (Phase 4 target)

- Ollama **v0.14.0+** natively serves the Anthropic Messages API at `/v1/messages`, expressly
  to let Claude Code / Anthropic SDK apps target local models via a base-URL change
  ([Ollama docs](https://docs.ollama.com/api/anthropic-compatibility),
  [v0.14.0 release notes](https://github.com/ollama/ollama/releases/tag/v0.14.0),
  [Ollama blog](https://ollama.com/blog/claude)). CLAUDE.md §1's claim is accurate.
- `ANTHROPIC_BASE_URL` pointed at a non-first-party host disables MCP tool search by default
  (`ENABLE_TOOL_SEARCH=true` re-enables if the proxy forwards `tool_reference` blocks)
  [docs env-vars].

## Auth / commercial posture

- Agent SDK docs instruct API-key auth and state third-party products may **not** offer
  claude.ai-login-backed usage; additionally, from **June 15, 2026** Agent SDK / `claude -p`
  usage on subscription plans draws from a separate monthly Agent SDK credit [docs overview].
  CLAUDE.md §1's "API key, not subscription" rule matches the docs.

## Explicitly unverified (deferred, not skipped silently)

- **WebFetch/WebSearch behavior against a local endpoint** (CLAUDE.md §1 asks for this in
  Session 0): no Ollama instance or model weights can run in this remote container, so the
  runtime check is **deferred to Phase 4** when a local endpoint exists. What the docs do
  establish: WebSearch is an Anthropic-hosted server-side tool (`web_search`), so it cannot
  exist against a local `/v1/messages` server — local/hybrid profiles need MCP-based search,
  as CLAUDE.md already specifies. WebFetch's exact behavior against a local endpoint remains
  to be tested empirically.
- Live behavior of `error_max_budget_usd` and per-model `model_usage` shapes will be
  re-confirmed against real sessions in the Phase 2 smoke test (zero LLM calls are made in
  Phase 1).
