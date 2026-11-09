# MCP CLIENTS

One install, then every harness starts the same STDIO server:

```powershell
python -m pip install .
microwind-mcp
```

If `microwind-mcp` is not on `PATH`, use the module form instead:

```text
command: python
args: ["-m", "microwind.server_app"]
```

Both forms are pathless. Replace the `<...>` placeholders; never commit real machine
paths or secrets.

## Shared environment

| Variable | Required | Meaning |
|---|---|---|
| `MICROWIND_HOME` | for application tools | Microwind 3.5 product folder (`system/Microwind35.exe`) |
| `DSCH_HOME` | for DSCH application tools | DSCH 3.5 product folder (`system/Dsch35.exe`) |
| `MICROWIND_MCP_PROJECTS` | for writes | directories mutating tools may write under |
| `MICROWIND_MCP_READONLY` | optional | `1` refuses every write |

The file, geometry, compiler, drawing and simulation tools work without the applications.
Start with `microwind_detect_installation` and `microwind_get_layers`; both are read-only.

## Claude Code

Project-scoped `.mcp.json` at the repository root:

```json
{
  "mcpServers": {
    "microwind": {
      "type": "stdio",
      "command": "microwind-mcp",
      "env": {
        "MICROWIND_HOME": "<path-to-microwind35-full>",
        "DSCH_HOME": "<path-to-dsch35-full>",
        "MICROWIND_MCP_PROJECTS": "<path-to-your-project>"
      }
    }
  }
}
```

Or via the CLI:

```bash
claude mcp add --transport stdio microwind -- microwind-mcp
```

Claude Code exposes the tools as `mcp__microwind__<tool>`. Project servers need approval
on first use; `/mcp` shows the connection state.

## Codex

`~/.codex/config.toml` (or a trusted project `.codex/config.toml`):

```toml
[mcp_servers.microwind]
command = "microwind-mcp"
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.microwind.env]
MICROWIND_HOME = "<path-to-microwind35-full>"
DSCH_HOME = "<path-to-dsch35-full>"
MICROWIND_MCP_PROJECTS = "<path-to-your-project>"
```

Codex does not forward the whole ambient environment to stdio servers; list every value
the server needs in `[mcp_servers.microwind.env]`.

## OpenCode

`opencode.json` at the repository root, or the user-level config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "microwind": {
      "type": "local",
      "command": ["microwind-mcp"],
      "enabled": true,
      "environment": {
        "MICROWIND_HOME": "<path-to-microwind35-full>",
        "DSCH_HOME": "<path-to-dsch35-full>",
        "MICROWIND_MCP_PROJECTS": "<path-to-your-project>"
      }
    }
  }
}
```

`type` is `local` for a stdio child process; `command` is an argv array, not a shell
string.

## DSH

DeepSeek Harness uses the official MCP client bridge. Add one row to the intended profile
patch (`cordis.patch.yml`):

```yaml
- insert:
    - id: microwind
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: microwind
        transport: stdio
        command: microwind-mcp
        args: []
        env:
          MICROWIND_HOME: <path-to-microwind35-full>
          DSCH_HOME: <path-to-dsch35-full>
          MICROWIND_MCP_PROJECTS: <path-to-your-project>
```

DSH exposes the tools as `mcp__microwind__<tool>`. It bridges MCP tools only; this server
does not expose resources or prompts.

## Any other STDIO client

```json
{
  "command": "microwind-mcp",
  "args": [],
  "env": {
    "MICROWIND_HOME": "<path-to-microwind35-full>",
    "DSCH_HOME": "<path-to-dsch35-full>",
    "MICROWIND_MCP_PROJECTS": "<path-to-your-project>"
  }
}
```

The server speaks JSON-RPC on stdin/stdout. stdout carries protocol traffic only; logs go
to stderr.

## Tool-call contract

* Every tool returns a JSON object. Failures return `{"ok": false, "error": "..."}`.
* `path` arguments are absolute or relative to the server process working directory.
* Mutating tools additionally require the resolved path to be inside
  `MICROWIND_MCP_PROJECTS`; otherwise they refuse instead of writing.
* `microwind_run_checks` is an independent geometric checker, not Microwind native DRC.
* `microwind_simulate_cell` runs ngspice, not Microwind's built-in simulator.

Minimum read-only smoke sequence in any client:

```text
microwind_detect_installation()
microwind_get_layers()
microwind_list_projects()
```

Then pass a returned project path to `microwind_read_layout` or
`microwind_validate_file`. Writes such as `microwind_generate_cmos_gate` and
`microwind_compile_cell` should wait until `MICROWIND_MCP_PROJECTS` is configured.
