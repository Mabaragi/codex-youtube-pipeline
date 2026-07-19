# Codex SDK Runtime Compatibility

The Python SDK and the `codex app-server` executable form one compatibility
unit. The normal runtime path uses the CLI bundled by `openai-codex` through
its `openai-codex-cli-bin` dependency. Leave `CODEX_CLI_CODEX_BIN` unset unless
an operator intentionally activates the external-CLI escape hatch below.

The current project baseline is `openai-codex` 0.144.x. The dependency lock
selects SDK 0.144.4 and its matching bundled CLI 0.144.4. The local native
pipeline also supplies per-server `enabled=false` entries through
`CODEX_CLI_CODEX_CONFIG_OVERRIDES`; its structured generation prompts do not
need personal or project MCP tools.

## Why the External-CLI Escape Hatch Exists

At times, a newly released model is available in a newer Codex CLI before the
official Python SDK publishes a matching bundled runtime. The service can
temporarily bypass the bundle by setting an explicit executable:

```text
CODEX_CLI_CODEX_BIN=C:\Users\operator\AppData\Roaming\npm\codex.cmd
```

`CliSettings.codex_bin` passes that path to `CodexConfig`, so every SDK call
starts the selected executable with `app-server --listen stdio://`. This
workaround can expose a newer model without changing the application's SDK
adapter, provided the newer app-server protocol remains backward-compatible.

This is an escape hatch, not the default upgrade path. The typed Python SDK
validates app-server request and response shapes generated for its matching
runtime. A separately upgraded CLI can change those shapes even when process
startup and account lookup still succeed.

## Known Failure Mode

Codex Desktop, a global CLI, and SDK-launched app-server processes can use the
same user-level `models_cache.json`. Different runtime versions may not accept
the same cache schema. A typical failure sequence is:

1. Another Codex runtime refreshes the shared model cache.
2. The externally selected CLI cannot parse the refreshed entry and falls back
   to an online model-list request.
3. Concurrent prompt calls start several app-server processes, multiplying
   cache reads, refreshes, plugin startup, and process shutdown.
4. Thread initialization or SDK response validation fails before `turn/start`.

Observed signatures include a missing `supports_reasoning_summaries` cache
field, model-refresh child-process timeouts, and app-server sessions that emit
`thread/started` but never reach `turn/start`. The application currently
translates the underlying exception to `Codex runtime operation failed.`, so
app-server logs are needed to distinguish this compatibility failure from an
account or model-generation failure.

App-server thread initialization also reads enabled MCP servers from the
operator's Codex configuration. An unreachable optional MCP can make account
lookup succeed while each `thread/start` waits through network discovery and
connection timeouts. This is independent of the SDK/CLI version mismatch but
is amplified by the same per-window app-server concurrency. Setting
`CODEX_CLI_CODEX_CONFIG_OVERRIDES` to a JSON list such as
`["mcp_servers.example.enabled=false"]` disables that server only for SDK
processes without editing the operator's global Codex configuration. An empty
`mcp_servers={}` override is insufficient because CLI configuration layers
merge nested tables; enumerate the configured server names instead.

## Selecting and Verifying a Runtime

Inspect the SDK and bundled runtime selected by the lock:

```powershell
uv tree --package openai-codex
uv run python -c "import subprocess; from codex_cli_bin import bundled_codex_path; subprocess.run([str(bundled_codex_path()), '--version'], check=True)"
```

When the bundled CLI supports the required models, remove
`CODEX_CLI_CODEX_BIN` from `.home-deploy/local.env`, run `uv sync --locked`,
set `CODEX_CLI_CODEX_CONFIG_OVERRIDES` to disable this host's unrelated MCP
servers, and restart the drained runtime. This restores the supported
SDK-to-CLI pair and keeps unrelated MCP startup outside structured generation
calls.

If a future model requires the escape hatch:

1. Drain the service before changing the executable.
2. Record the SDK, bundled CLI, and external CLI versions.
3. Set `CODEX_CLI_CODEX_BIN` only in the ignored local environment file.
4. Keep unrelated MCP servers disabled through
   `CODEX_CLI_CODEX_CONFIG_OVERRIDES` unless the generation prompt explicitly
   needs one of their tools.
5. Verify account lookup, one `thread/start`, and one complete no-publication
   prompt turn before resuming workers.
6. Keep worker concurrency low until the smoke test succeeds.
7. Remove the override as soon as a matching official SDK is available.

Do not commit a machine-specific executable path. The tracked environment
template leaves the override commented out and points operators back to this
document.

## Upgrade Procedure

Upgrade the SDK and bundled CLI together:

```powershell
.\scripts\local-home\runtime.ps1 drain
uv lock --upgrade-package openai-codex
uv sync --dev --locked
uv tree --package openai-codex
```

Review SDK API changes, run the backend quality gates, then perform a local
Codex smoke test before resuming automated micro-event and timeline work. A
successful package installation alone does not prove app-server protocol,
authentication, model availability, or structured-output compatibility.
