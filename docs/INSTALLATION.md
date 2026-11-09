# INSTALLATION

## Requirements

| Item | Version / notes |
|---|---|
| Windows | required only for the application-control tools (screenshots, launch, File→Open) |
| Python | 3.10+ (developed and tested on 3.13.15) |
| `mcp` | `>=1.0,<2` — **pin matters**: mcp 2.x removed `mcp.server.fastmcp` |
| `Pillow` | `>=10`, rendered drawings and report images |
| `pytest` | `>=8`, development only |
| Microwind 3.5 | product folder containing `system/Microwind35.exe` (no default path) |
| DSCH 3.5 | product folder containing `system/Dsch35.exe` (no default path) |

Nothing else. No pywinauto, no pyautogui, no GUI automation dependency — window control
and screenshots use `ctypes` and the .NET screenshot API that ships with Windows. Pillow
is used only to render generated drawings and report images.

## Install

```powershell
python -m pip install .
microwind-mcp                    # speaks MCP over stdio
```

From a checkout you can also run `python server.py`, which imports the same package
entry point. The installed console command is what MCP clients should use; it needs no
absolute path in their configuration.

Optional report helpers (not exposed as MCP tools) install with
`python -m pip install .[report]`.

`microwind-mcp` prints nothing to stdout; diagnostics go to stderr, and to a log file if
`log_file` is configured.

## Configuration

Resolution order — later wins:

1. built-in behavior: no machine-specific install paths are assumed
2. `microwind-mcp.json` (or `config.json`) in the working directory
3. environment variables

The application tools need `MICROWIND_HOME` and `DSCH_HOME` unless a config file supplies
them. File, geometry, compiler, drawing and simulation tools still work without the
applications; detection reports `installed: false` instead of inventing a path.

| Variable | Meaning |
|---|---|
| `MICROWIND_HOME` | Microwind product root (containing `system/`, `Examples/`, `rules/`) |
| `DSCH_HOME` | DSCH product root (containing `system/`, `examples/`, `rules/`) |
| `MICROWIND_MCP_CONFIG` | path to the JSON config |
| `MICROWIND_MCP_PROJECTS` | `os.pathsep`-separated list of directories writes are allowed in |
| `MICROWIND_MCP_READONLY` | `1` refuses every mutating tool |
| `MICROWIND_MCP_LOGLEVEL` | `DEBUG` / `INFO` / `WARNING` (default `INFO`) |
| `LIBREOFFICE_PATH` | optional `soffice` executable for DOCX→PDF fallback |

`microwind-mcp.json`:

```json
{
  "microwind_home": "<path-to-microwind35-full>",
  "dsch_home": "<path-to-dsch35-full>",
  "project_dirs": ["./projects"],
  "default_tech": "cmos012.rul",
  "log_file": "./logs/server.log",
  "readonly": false
}
```

Project directories are the write boundary. A write creates the target's parent directory;
the configured roots may be absent until the first write. A write outside them is refused
with a clear error; widen the list rather than fighting it.

## Verify the installation

```powershell
python -c "from microwind.install import detect; import json; print(json.dumps(detect(), indent=1))"
python scripts/roundtrip_report.py     # 245 MSK + 53 SCH + 96 SYM byte-identical
python scripts/mcp_smoke.py --list     # 32 tools
```

Set `MICROWIND_HOME` and `DSCH_HOME` before the fixture-driven checks. If detection fails,
the server still works for file/layout/geometry tools; only the application tools need the
applications.

## Client setup

See [CLIENTS.md](CLIENTS.md) for Claude Code, Codex, OpenCode, DSH and a generic STDIO
entry. Every example runs `microwind-mcp` from `PATH` and uses placeholder environment
values, so no local path is committed.

Quick sanity check without a client:

```powershell
python scripts/mcp_smoke.py            # drives initialize + tools/list + 15 tool calls
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: mcp.server.fastmcp` | mcp 2.x installed. `pip install "mcp>=1.0,<2"` |
| `ModuleNotFoundError: microwind_tools` | run `python -m pip install .` or run from the checkout root |
| `path … is outside the allowed project directories` | add it to `project_dirs` / `MICROWIND_MCP_PROJECTS` |
| `server is read-only` | `MICROWIND_MCP_READONLY` is set; unset it |
| `Microwind is not installed or was not detected` | set `MICROWIND_HOME` to the folder containing `system\Microwind35.exe` |
| `File->Open dialog did not appear` | the app must be foreground-capable; run the tool with the session unlocked and only one instance open |
| `loaded: false` but no error | the window title did not show the document — check `microwind_window_state` for a dialog |
| Screenshot is black | the desktop is locked / RDP disconnected; the capture is a real screen grab and cannot work without a visible session |
| Tool write silently overwrote nothing | writes always create `<name>.bak[N]` first — look beside the file |
