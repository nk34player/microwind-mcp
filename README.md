# microwind-mcp

MCP server that lets an AI agent work with **Microwind 3.5** layouts and **DSCH 3.5**
schematics: parse and edit native files without losing anything it does not understand,
generate CMOS cells and power grids, run independent geometric checks, and drive the real
Windows applications.

Verified against a real Microwind 3.5 install: 245 `.MSK` layouts, 53 `.sch`
schematics, 96 `.sym` symbols as ground truth.

## What it actually does

| Area | Capability |
|---|---|
| Native files | Byte-exact `.MSK` / `.sch` / `.sym` parse + re-emit (loss-preserving; unknown records kept verbatim) |
| Technology | Read `.rul` (16 files) and `.tec` (8 files): lambda, metal stack, `cif` map, rule values, SPICE model parameters |
| Layout editing | create / add rectangle / add label / move / resize / remove, with backup before every write |
| Power grid | Parametric VDD/VSS grid, per-layer widths, margins, vias on same-supply crossings, collision detection, auto-placement, preservation proof |
| CMOS cells | `inverter`, `nand2`, `nor2` generated from `.rul`-derived geometry, structurally verified (no shorts, no opens) |
| Verification | Independent min-width / spacing / overlap / connectivity / power-net checks, always labelled *not* native DRC |
| DSCH | Schematic read, component/pin/net extraction, structural validation, symbol-library inventory |
| Compiler | One-line boolean expression -> transistor netlist -> native `.MSK` (complex gates + NAND/NOR/INV decomposition, unit-inverter sizing, body ties) |
| Simulation | Vendor `spice.lib` models + ngspice: waveform PNG, SPICE-sampled truth table, per-input tpLH/tpHL |
| Drawings | Transistor schematic, layout, device zoom, stick view and layered cross-sections as PNG |
| Applications | Detect installs, launch Microwind/DSCH, load a document through File→Open, screenshot the live window, close only the PID it started |

Not implemented in this build: Verilog/SPICE generation, native DRC invocation,
DSCH→layout compilation, reports.

## Install

```powershell
python -m pip install .          # installs the `microwind-mcp` command
microwind-mcp                    # starts the STDIO MCP server
```

From a checkout you can also run `python server.py`. Set `MICROWIND_HOME` and
`DSCH_HOME` to the two product folders. No machine-specific paths are built in.

Windows-only for the application-control tools; the file/format/geometry tools are
portable Python.

Client setup (Claude Code, Codex, OpenCode, DSH, any STDIO client):
[CLIENTS.md](docs/CLIENTS.md). Installation details: [INSTALLATION.md](docs/INSTALLATION.md).

Microwind and DSCH are commercial products of Microwind/INSA; this project ships no
vendor files.
