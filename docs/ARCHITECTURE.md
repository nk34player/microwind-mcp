# ARCHITECTURE

## Design principle

The applications expose **no scripting interface**. That is not an assumption: the 3.5
manual, its 31 help pages and the vendor's own command line were checked (see
`docs/RESEARCH.md` §0.1). The only durable automation surface is the text formats, so the
architecture is a **file-format engine** with a thin, verified GUI supplement.

Consequence: every capability must be provable from a file plus a geometric model, not
from "the app was told to do it".

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│ MCP client (Claude Code / OpenCode / any STDIO client)       │
└───────────────────────────┬──────────────────────────────────┘
                            │ JSON-RPC over stdio (stdout only)
┌───────────────────────────▼──────────────────────────────────┐
│ microwind/server_app.py — FastMCP registry, schemas, _guard() │
│ logging → stderr / optional file                              │
└───────┬──────────────────────────────┬───────────────────────┘
        │                              │
┌───────▼───────────────┐   ┌──────────▼─────────────┐   ┌────────────────┐
│ microwind_tools/      │   │ microwind_tools/       │   │ microwind_tools│
│ layout_tools.py       │   │ app_tools.py           │   │ dsch_tools.py  │
│ files, geometry,      │   │ launch, File→Open,     │   │ .sch/.sym parse │
│ power grid, CMOS,     │   │ screenshot, close PID  │   │ nets, symbols   │
│ checks                │   │                        │   │                 │
└───────┬───────────────┘   └──────────┬─────────────┘   └────────┬────────┘
        │                              │                          │
┌───────▼──────────────────────────────▼──────────────────────────▼────────┐
│ microwind/*  — pure library, no MCP, no I/O side effects except save()    │
└──────────────────────────────────────────────────────────────────────────┘
```

`microwind/*` knows nothing about MCP; `microwind_tools/*` knows nothing about transport;
`microwind/server_app.py` owns only registration. That is what makes 68 tests over real
fixtures possible without a GUI.

## The loss-preserving record model

Everything hinges on one rule: **a parser must not lose a byte it did not understand.**

1. Read bytes → decode latin-1 → split on `\n`, keeping each line's own terminator.
2. Assemble *logical* records by parenthesis balance (DSCH splits `REC(` across lines in
   `Clk24H00.sch`; a naive line parser corrupts it).
3. Classify by keyword. Known records get parsed fields; every record keeps `raw`.
4. Writer re-emits: untouched records from `raw`, modified records regenerated, unknown
   records from `raw`.

Round-trip proof: 245 `.MSK` + 53 `.sch` + 96 `.sym`, byte-identical (see
`scripts/roundtrip_report.py`).

## Compiler, drawings and simulation

Microwind 3.5 exposes no automation interface: a CLI document argument is ignored
(measured), the executable imports no COM/DDE server, and `Silicon.exe` is a Delphi form,
not a CLI.  Real work is therefore done at the file level:

* `logic.py` parses the Compile-One-Line syntax (`system/compiler.ini`), builds the
  pull-down network from NOT(F), derives the pull-up as its dual, and falls back to
  NAND/NOR/INV decomposition when NOT(F) is not monotone.  Each transistor's width is
  the unit device multiplied by the number of series devices on its worst path.
* Layout comes from the same `.rul` numbers as `cmos.py`; every net gets one metal1 track
  and metal2 stubs, so crossings are not shorts by construction.  Body ties connect the
  n-diffusion to VSS and a p-diffusion inside the nwell to VDD.
* `spice.py` writes an ngspice deck from the same transistor list with the vendor
  `spice.lib` LEVEL=3 cards, samples the truth table after settled clocks, and measures
  tpLH/tpHL per input by pulsing one input at a time.
* `draw.py` / `report.py` render schematic, layout, stick view, cross-sections and
  waveforms and assemble a PDF.  These are renderings of our own data, never screenshots.

## Geometry and connectivity

* Coordinates are integer **lambda** units; `.rul` `lambda` converts to µm.
* Rectangles union per layer to form components; a via rect touching both adjacent metals
  joins their components.
* Neighbour queries use a 64λ spatial bucket grid (`checks._index`), which took the worst
  case from 53 s to 6 s for a 19,628-rectangle layout.
* Point labels attach by point-in-shape hit test (the behaviour observed in real files).
* Same-layer duplicates are *normal* (Microwind's via tool stamps fresh pads), so
  duplicate identical rectangles are excused from overlap findings.

## Lazy but honest choices

| Decision | Why |
|---|---|
| ctypes instead of pywinauto/pyautogui | no dependency; the app-control tools are optional verification, not the working path |
| PowerShell .NET screenshot | no Python imaging dependency, one call |
| `check_only` power-grid mode | lets an agent see collisions before committing |
| auto-place grid when colliding | mirrors Microwind's own compiler behaviour ("shift right until free") |
| Single device row + M2 stubs + M3 input rails | guarantees no stub crossing, so connectivity never depends on a routing heuristic |
| `_guard()` wrapper | every failure becomes `{"ok": false, "error": "..."}` instead of a traceback into the protocol |

## Safety model

* `MICROWIND_MCP_READONLY=1` refuses every write (`microwind/safety.py`).
* Writes are confined to configured project directories (`resolve_in_roots`).
* Every overwrite copies the target to `<name>.bak[N]` first.
* Writes are staged to a temp file and `os.replace`d with retries (Windows AV/indexer
  holds targets open; WinError 5/32).
* Process control only terminates PIDs this server started.
* No tool accepts a shell command; nothing is executed from tool input.

## Extension points

* New record kinds: add a subclass of `Record` in `msk.py`; unknown forms keep working.
* New cells: add a netlist to `cmos.NETLISTS`; the slot router and verifier are generic.
* New checks: add a function to `checks.py` and include it in `run_all`.
* Native DRC, when implemented, must set `native_drc_run: true` and stop reusing the
  independent-response shape.
