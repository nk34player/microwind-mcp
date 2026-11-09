#!/usr/bin/env python3
"""Microwind + DSCH MCP server (STDIO).

Every tool is backed by a real implementation in `microwind_tools/`; nothing is a placeholder.
Diagnostics go to stderr (and optionally a log file) so stdout stays a clean JSON-RPC
channel — strict clients close the transport on a single stray byte.

Run:      python server.py
Config:   microwind-mcp.json (or MICROWIND_MCP_CONFIG), plus MICROWIND_HOME / DSCH_HOME.
Read-only: set MICROWIND_MCP_READONLY=1 to refuse every write.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

import microwind_tools.app_tools as apps
import microwind_tools.dsch_tools as dsch
import microwind_tools.layout_tools as layouts
import microwind_tools.logic_tools as logic
from microwind.config import load_config
from microwind.safety import SafetyError

LOG = logging.getLogger("microwind_mcp")


def _configure_logging() -> None:
    cfg = load_config()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if cfg.log_file:
        cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(cfg.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=os.environ.get("MICROWIND_MCP_LOGLEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


_configure_logging()
mcp = FastMCP(
    "microwind-mcp",
    instructions=(
        "Microwind 3.5 / DSCH 3.5 tooling. Call microwind_detect_installation first to "
        "learn whether the applications and technology files are available. All layout "
        "and schematic paths are absolute paths or paths relative to the server process "
        "working directory. Mutating tools only accept paths inside the configured "
        "project directories (MICROWIND_MCP_PROJECTS); set MICROWIND_MCP_READONLY=1 to "
        "refuse every write. Prefer the file-level tools (generate, edit, checks, "
        "drawings, simulation) over GUI automation. Never claim native Microwind DRC: "
        "microwind_run_checks is an independent geometric checker."
    ),
)


def _guard(func, *args, **kwargs):
    """Uniform structured errors: callers get {"ok": false, "error": ...}, never a traceback."""
    try:
        result = func(*args, **kwargs)
        if isinstance(result, dict) and "ok" not in result:
            result["ok"] = True
        return result
    except (FileNotFoundError, ValueError, SafetyError, RuntimeError) as exc:
        LOG.warning("tool error: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:                                    # noqa: BLE001 - reported
        LOG.exception("unexpected tool failure")
        return {"ok": False, "error": f"unexpected {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# installation & application control
# ---------------------------------------------------------------------------

@mcp.tool()
def microwind_detect_installation() -> dict:
    """Detect Microwind 3.5 and DSCH 3.5: executable paths, rule files, example counts.

    Read-only. Returns `installed` per product plus the project directories that writes
    are allowed in, and whether the server is in read-only mode.
    """
    return _guard(layouts.detect_installation)


@mcp.tool()
def dsch_detect_installation() -> dict:
    """Detect DSCH 3.5 and report its `.tec` technologies and schematic/symbol fixtures."""
    info = _guard(layouts.detect_installation)
    return {"ok": info.get("ok", True), "dsch": info.get("dsch"), "config": info.get("config")}


@mcp.tool()
def microwind_open(path: str = "", settle: float = 5.0) -> dict:
    """Launch Microwind 3.5 and optionally open a `.MSK` layout through File -> Open.

    Modifies process state, not files. `loaded` is true only when the window title shows
    the requested document and no modal dialog appeared.
    """
    return _guard(apps.open_microwind, path or None, settle)


@mcp.tool()
def dsch_open(path: str = "", settle: float = 5.0) -> dict:
    """Launch DSCH 3.5 and optionally open a `.sch` schematic through File -> Open."""
    return _guard(apps.open_dsch, path or None, settle)


@mcp.tool()
def microwind_window_state(pid: int = 0) -> dict:
    """Report visible windows (titles verbatim), modal dialogs and tracked processes."""
    return _guard(apps.window_state, pid or None)


@mcp.tool()
def microwind_screenshot(output: str) -> dict:
    """Capture the current desktop to a PNG file and return its path and size."""
    return _guard(apps.screenshot, output)


@mcp.tool()
def microwind_close(pid: int) -> dict:
    """Terminate exactly the given PID if this server started it; refuses unknown PIDs."""
    return _guard(apps.close_application, pid)


# ---------------------------------------------------------------------------
# files & layouts
# ---------------------------------------------------------------------------

@mcp.tool()
def microwind_list_projects(directory: str = "", limit: int = 200) -> dict:
    """List `.MSK` layouts and `.sch` schematics under the project directories."""
    return _guard(layouts.list_projects, directory or None, limit)


@mcp.tool()
def microwind_read_layout(path: str) -> dict:
    """Summarise a layout: rectangle/label counts, layers, bbox, size in lambda and µm."""
    return _guard(layouts.read_layout, path)


@mcp.tool()
def microwind_parse_layout(path: str, limit: int = 200, kind: str = "") -> dict:
    """Dump the raw record stream of a layout, optionally filtered by record kind (REC, TITLE…)."""
    return _guard(layouts.parse_layout, path, limit, kind or None)


@mcp.tool()
def microwind_validate_file(path: str) -> dict:
    """Structural validation of a `.MSK`/`.sch`/`.sym` file. Not electrical verification."""
    return _guard(layouts.validate_file, path)


@mcp.tool()
def microwind_create_layout(path: str, width: int = 200, height: int = 200) -> dict:
    """Create a new empty layout with a valid `VERSION/FIG/BB/SIMU/ZOOM/FFIG` skeleton."""
    return _guard(layouts.create_layout, path, width, height)


@mcp.tool()
def microwind_add_rectangle(path: str, x: int, y: int, w: int, h: int, layer: str, extra: int = -1) -> dict:
    """Add a `REC` rectangle on `layer` at (x,y) with size (w,h) in lambda units."""
    return _guard(layouts.add_rectangle, path, x, y, w, h, layer, None if extra < 0 else extra)


@mcp.tool()
def microwind_add_label(path: str, x: int, y: int, text: str, code: str = "$-") -> dict:
    """Add a net label with the confirmed `TITLE` + `$` code syntax ($1 VDD, $0 VSS)."""
    return _guard(layouts.add_label, path, x, y, text, code)


@mcp.tool()
def microwind_modify_layout(
    path: str,
    move: list[dict] | None = None,
    resize: list[dict] | None = None,
    remove: list[dict] | None = None,
) -> dict:
    """Move/resize/remove rectangles matched by `{x, y[, layer]}`; other records untouched."""
    return _guard(layouts.modify_layout, path, move, resize, remove)


@mcp.tool()
def microwind_get_layers() -> dict:
    """List all layer codes with names/kinds, via pairings and metal indices."""
    return _guard(layouts.get_layers)


@mcp.tool()
def microwind_get_technology(path: str = "") -> dict:
    """Return the parsed technology: lambda, metal layers, cif map, selected design rules."""
    return _guard(layouts.get_technology, path or None)


@mcp.tool()
def microwind_layers_used(path: str) -> dict:
    """Layer histogram for one layout, with unknown codes called out explicitly."""
    return _guard(layouts.describe_layers_used, path)


# ---------------------------------------------------------------------------
# power grid
# ---------------------------------------------------------------------------

@mcp.tool()
def microwind_generate_power_grid(
    path: str = "",
    new_file: str = "",
    layers: list[str] | None = None,
    width: int = 200,
    height: int = 200,
    columns: int = 4,
    rows: int = 3,
    wire_width: int = 4,
    rail_widths: dict[str, int] | None = None,
    margin: int = 0,
    offset_x: int = 0,
    offset_y: int = 0,
    voltage_pattern: list[str] | None = None,
    via_size: int = 2,
    via_pad: int = 4,
    check_only: bool = False,
) -> dict:
    """Generate a VDD/VSS power grid on an existing layout (`path`) or a new one (`new_file`).

    Odd-listed layers become vertical columns, even-listed ones horizontal rows; vias are
    placed only where both rails carry the same supply. Collisions with existing same-layer
    geometry are detected first and the grid is shifted right, like Microwind's compiler.
    With `check_only` nothing is written.
    """
    return _guard(
        layouts.generate_power_grid, path or None, layers, width, height, columns, rows,
        wire_width, rail_widths, None, None, margin, (offset_x, offset_y), voltage_pattern,
        via_size, via_pad, True, check_only, new_file or None,
    )


@mcp.tool()
def microwind_generate_power_rails(
    path: str,
    layer: str = "ME",
    count: int = 4,
    pitch: int = 40,
    length: int = 150,
    width: int = 4,
    vertical: bool = True,
    net: str = "VDD",
) -> dict:
    """Generate one bundle of parallel power rails on a single metal layer."""
    return _guard(layouts.generate_power_rails, path, layer, count, pitch, length, width, vertical, net)


@mcp.tool()
def microwind_analyze_power_grid(path: str) -> dict:
    """Report rails, power labels and the connected components that carry VDD/VSS."""
    return _guard(layouts.analyze_power_grid, path)


# ---------------------------------------------------------------------------
# CMOS cells & verification
# ---------------------------------------------------------------------------

@mcp.tool()
def microwind_list_gate_types() -> dict:
    """List the CMOS cells this server can generate and their device netlists."""
    return _guard(layouts.list_gate_types)


@mcp.tool()
def microwind_generate_cmos_gate(gate: str, path: str) -> dict:
    """Generate `inverter`, `nand2` or `nor2` from `.rul`-derived geometry, then verify it."""
    return _guard(layouts.generate_cmos_gate, gate, path)


@mcp.tool()
def microwind_run_checks(path: str, tech: str = "") -> dict:
    """Run independent geometric checks: min width, spacing, overlaps, connectivity, power.

    This is NOT Microwind's native DRC; the report says so, and `native_drc_run` is false.
    """
    return _guard(layouts.run_checks, path, tech or None)


# ---------------------------------------------------------------------------
# logic compiler, drawings and simulation (native, no GUI automation)
# ---------------------------------------------------------------------------

@mcp.tool()
def microwind_compile_cell(expression: str, path: str, tech: str = "") -> dict:
    """Compile `out=<expression>` (Microwind Compile-One-Line syntax) into a native .MSK.

    Complex gates are built from NOT(F); non-monotone functions are decomposed into
    NAND/NOR/INV stages.  Every stage is sized to the unit inverter (4/2 n, 8/2 p).
    Body ties are included and the independent rule checks run on the result.
    """
    return _guard(logic.compile_cell, expression, path, tech or None)


@mcp.tool()
def microwind_draw_cell(expression: str, output_dir: str, kind: str = "all",
                        tech: str = "") -> dict:
    """Render schematic, layout, stick diagram and cross-section PNGs for an expression."""
    return _guard(logic.draw_cell, expression, output_dir, kind, tech or None)


@mcp.tool()
def microwind_cross_section(path: str, output: str, axis: str = "y", at: int = 2,
                            start: int | None = None, end: int | None = None) -> dict:
    """Layered cross-section PNG of a layout cut at `y=at` (or `x=at`), in lambda units."""
    return _guard(logic.cross_section, path, output, axis, at, start, end)


@mcp.tool()
def microwind_simulate_cell(expression: str, output_dir: str, models: str = "",
                            vdd: float = 1.2, cload_fF: float = 1.0,
                            delays: bool = True) -> dict:
    """Simulate the compiled transistor netlist with ngspice: truth table, waves, delays.

    Uses the vendor `spice.lib` models.  Labelled ngspice - this is not Microwind's
    built-in SPICE, which has no automation interface.
    """
    return _guard(logic.simulate_cell, expression, output_dir, models or None,
                  vdd, cload_fF, delays)


# ---------------------------------------------------------------------------
# DSCH schematics
# ---------------------------------------------------------------------------

@mcp.tool()
def dsch_read_schematic(path: str, include_nets: bool = False, limit: int = 100) -> dict:
    """Read a DSCH schematic: components, pins, wires, embedded Verilog and validation."""
    return _guard(dsch.read_schematic, path, include_nets, limit)


@mcp.tool()
def dsch_validate_schematic(path: str) -> dict:
    """Structural validation of a `.sch`/`.sym`: DSCH header, SYM/FSYM balance, pins."""
    return _guard(dsch.validate_schematic, path)


@mcp.tool()
def dsch_list_symbols(limit: int = 200) -> dict:
    """List the DSCH 3.5 `.sym` symbol library that ships with the installation."""
    return _guard(dsch.list_symbols, limit)


@mcp.tool()
def dsch_schematic_netlist(path: str) -> dict:
    """Derive nets from schematic wire geometry: pins grouped by electrical connectivity."""
    return _guard(dsch.schematic_netlist, path)


def main() -> int:
    LOG.info("starting microwind-mcp (stdio)")
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
