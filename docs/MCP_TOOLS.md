# MCP TOOLS

32 tools, all backed by real implementations (verified by `scripts/mcp_smoke.py`, output in
`docs/MCP_SMOKE_OUTPUT.json`). Labels:

* **Implemented+Tested** — exercised against real 3.5 fixtures in `tests/` or the smoke run.
* **Implemented-Unverified** — code exists and runs, but its correctness depends on the
  application behaving as observed once; no automated proof.
* **Out-of-scope** — deliberately absent (no stub exists, so a client cannot call a lie).

Every tool returns a JSON object. Failures return `{"ok": false, "error": "..."}`; success
adds `"ok": true` when the payload does not already carry status.

## Installation & application control

| Tool | What it does | Writes files | Operates the app | Status |
|---|---|---|---|---|
| `microwind_detect_installation` | exe paths, rule files, example counts, project roots, read-only flag | no | no | Implemented+Tested |
| `dsch_detect_installation` | DSCH exe, `.tec` technologies, fixtures | no | no | Implemented+Tested |
| `microwind_open` | launch Microwind, File→Open a `.MSK`, report title + dialogs | no | yes | Implemented+Tested |
| `dsch_open` | launch DSCH, File→Open a `.sch` | no | yes | Implemented+Tested |
| `microwind_window_state` | visible windows, titles verbatim, modal dialogs, tracked PIDs | no | read-only | Implemented-Unverified |
| `microwind_screenshot` | whole-desktop PNG capture | PNG only | read-only | Implemented+Tested |
| `microwind_close` | terminate a PID **this server** started | no | yes | Implemented+Tested |

`microwind_open` returns `loaded: true` only when the window title shows the requested
document **and** no `#32770` dialog appeared. Anything else is reported, never assumed.

## Files & layouts

| Tool | What it does | Writes | Status |
|---|---|---|---|
| `microwind_list_projects` | list `.MSK`/`.sch` under project dirs with sizes | no | Implemented+Tested |
| `microwind_read_layout` | rect/label counts, layers, bbox, size in λ and µm, components, header | no | Implemented+Tested |
| `microwind_parse_layout` | raw record dump, filterable by kind | no | Implemented+Tested |
| `microwind_validate_file` | structural validation for `.MSK`/`.sch`/`.sym` | no | Implemented+Tested |
| `microwind_create_layout` | new layout with a valid header | yes | Implemented+Tested |
| `microwind_add_rectangle` | add `REC(x,y,w,h,LAYER[,extra])` | yes | Implemented+Tested |
| `microwind_add_label` | add `TITLE` + `$` code (`$1` VDD, `$0` VSS) | yes | Implemented+Tested |
| `microwind_modify_layout` | move/resize/remove rects matched by `{x,y[,layer]}` | yes | Implemented+Tested |
| `microwind_get_layers` | 23 layer codes, kinds, via pairs, metal index | no | Implemented+Tested |
| `microwind_get_technology` | lambda, metal count, `cif` map, selected rules, model params | no | Implemented+Tested |
| `microwind_layers_used` | layer histogram with unknown codes called out | no | Implemented+Tested |

Every write: project-root confinement → backup of the previous file → atomic replace.

## Power grid

| Tool | What it does | Writes | Status |
|---|---|---|---|
| `microwind_generate_power_grid` | VDD/VSS grid on an existing layout or a new file | yes | Implemented+Tested |
| `microwind_generate_power_rails` | one bundle of parallel rails, single layer | yes | Implemented+Tested |
| `microwind_analyze_power_grid` | rails, power labels, connected components | no | Implemented+Tested |

`microwind_generate_power_grid` arguments: `path` **or** `new_file`, `layers` (odd index =
vertical columns, even = horizontal rows), `width`, `height`, `columns`, `rows`,
`wire_width`, `rail_widths` (per layer), `margin`, `offset_x/y`, `voltage_pattern`,
`via_size`, `via_pad`, `check_only`.

Behaviour, verified: collisions with existing same-layer geometry are detected first; the
grid is shifted right of the occupied area (like Microwind's compiler) or the call fails
with the collision list; `check_only: true` reports without writing.

## CMOS cells & verification

| Tool | What it does | Writes | Status |
|---|---|---|---|
| `microwind_list_gate_types` | the cells and their device netlists | no | Implemented+Tested |
| `microwind_generate_cmos_gate` | `inverter` / `nand2` / `nor2`, rule-derived geometry, verified | yes | Implemented+Tested |
| `microwind_run_checks` | independent width/spacing/overlap/connectivity/power checks | no | Implemented+Tested |

`microwind_run_checks` always returns `"engine": "independent-geometry-checks (not
Microwind native DRC)"` and `"native_drc_run": false`. It never claims native verification.

## Logic compiler, drawings, simulation

| Tool | What it does | Writes | Status |
|---|---|---|---|
| `microwind_compile_cell` | `out=<expr>` (Compile-One-Line syntax) -> native `.MSK`; complex gate when NOT(F) is monotone, else NAND/NOR/INV stages, unit-inverter sizing, body ties, well taps, clock/probe labels (`$c` on inputs A,B,C,D with binary-weighted periods, `$v` on the output), rule checks | `.MSK` | Implemented+Tested |
| `microwind_draw_cell` | transistor schematic, layout, device zoom, stick view, N/P cross-sections as PNG | PNGs | Implemented+Tested |
| `microwind_cross_section` | layered cut through an existing layout at `y`/`x` in lambda units | PNG | Implemented+Tested |
| `microwind_simulate_cell` | ngspice transient + truth table + tpLH/tpHL from the compiled netlist, vendor `spice.lib` models | deck, waves, PNG | Implemented+Tested |

These four replace GUI automation for real work: no clicks, no keystrokes, no window
state.  `microwind_simulate_cell` reports `simulator: "ngspice"` and never claims to be
Microwind's built-in SPICE.

## DSCH

| Tool | What it does | Writes | Status |
|---|---|---|---|
| `dsch_read_schematic` | components, pins, wires, embedded Verilog, element counts, problems | no | Implemented+Tested |
| `dsch_validate_schematic` | DSCH header, `SYM`/`FSYM` balance, duplicate pins at one point | no | Implemented+Tested |
| `dsch_list_symbols` | the 96-file `.sym` library with symbol names | no | Implemented+Tested |
| `dsch_schematic_netlist` | nets derived from wire geometry | no | Implemented+Tested |

## Absent by design

No tool exists for native DRC, Verilog/SPICE generation, DSCH schematic creation, layout
compaction, or reporting.

## Client configuration

Every client starts the same STDIO command, `microwind-mcp` (installed by
`python -m pip install .`). Setup for Claude Code, Codex, OpenCode, DSH and a generic
client is in [CLIENTS.md](CLIENTS.md). No absolute server path is needed.

The verified raw path is `scripts/mcp_smoke.py` and the STDIO handshake in
`tests/test_server.py`; both exercise the protocol directly.
