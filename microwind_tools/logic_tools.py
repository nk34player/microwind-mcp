"""Expression compiler, drawings and SPICE tools (native, no GUI automation)."""

from __future__ import annotations

from pathlib import Path

from microwind import draw, spice
from microwind.config import load_config
from microwind.install import find_dsch, find_microwind
from microwind.logic import check_circuit, synthesize
from microwind.rul import Technology
from microwind.safety import ensure_writable, resolve_in_roots

TECH_NAME = "cmos012.rul"


def _cfg():
    return load_config()


def _tech(path: str | None = None) -> Technology | None:
    if path:
        p = Path(path)
        return Technology.load(p) if p.is_file() else None
    mw = find_microwind(_cfg().microwind_home)
    if mw and mw.rules:
        preferred = next((p for p in mw.rules if p.name == TECH_NAME), mw.rules[0])
        return Technology.load(preferred)
    return None


def _models(path: str | None = None) -> Path:
    if path:
        return Path(path)
    dsch = find_dsch(_cfg().dsch_home)
    if dsch and dsch.rules:
        for rule in dsch.rules:
            if rule.name == "spice.lib":
                return rule
    raise spice.SpiceError("spice.lib not found; pass models= explicitly")


def _out(path: str) -> Path:
    ensure_writable()
    return resolve_in_roots(path, _cfg().roots())


def compile_cell(expression: str, path: str, tech: str | None = None) -> dict:
    """Compile a one-line boolean expression into a native .MSK layout.

    Syntax is Microwind's `Compile One Line`: `out=~((A&B&C)|D)` with `&`, `|`, `~`,
    `^`.  `~F` monotone becomes a single complex gate, otherwise the expression is
    decomposed into NAND/NOR/INV stages, each sized to the unit inverter.
    """
    circuit = synthesize(expression)
    technology = _tech(tech)
    report = check_circuit(circuit, technology)
    target = _out(path)
    created = not target.exists()
    circuit.msk.path = target
    circuit.msk.save(target, make_backup=not created)
    bbox = circuit.msk.bbox or (0, 0, 0, 0)
    return {
        "ok": report["ok"],
        "path": str(target),
        "created": created,
        "expression": circuit.expression,
        "inputs": circuit.inputs,
        "stages": circuit.stages,
        "devices": [d.to_dict() for d in circuit.devices],
        "rectangles": len(circuit.msk.rects),
        "lambda_um": technology.lam if technology else None,
        "size_lambda": [bbox[2] - bbox[0], bbox[3] - bbox[1]],
        "checks": report,
    }


def draw_cell(expression: str, out_dir: str, kind: str = "all",
              tech: str | None = None) -> dict:
    """Render schematic / layout / stick / cross-section PNGs for an expression."""
    circuit = synthesize(expression)
    out = _out(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    if kind in ("all", "schematic"):
        files["schematic"] = str(draw.schematic_png(circuit, out / "schematic.png"))
    if kind in ("all", "layout"):
        files["layout"] = str(draw.layout_png(circuit.msk, out / "layout.png", scale=4))
        files["layout_zoom"] = str(draw.layout_png(
            circuit.msk, out / "layout_zoom.png", scale=12, max_y=40, x_range=(4, 124)))
    if kind in ("all", "stick"):
        files["stick"] = str(draw.stick_png(circuit.msk, out / "stick.png", scale=10))
    if kind in ("all", "cross"):
        n_dev = len([d for d in circuit.devices if d.kind == "n"])
        p_first = 20 + (n_dev + 1) * 40
        files["section_n"] = str(draw.cross_section_png(
            circuit.msk, "y", 2, out / "section_n.png", span=(8, 88)))
        files["section_p"] = str(draw.cross_section_png(
            circuit.msk, "y", 2, out / "section_p.png", span=(p_first - 8, p_first + 72)))
    return {"ok": True, "expression": circuit.expression, "files": files}


def cross_section(path: str, output: str, axis: str = "y", at: int = 2,
                  start: int | None = None, end: int | None = None) -> dict:
    """Cut a layout along `y=at` (or `x=at`) and write the layered PNG."""
    from microwind.msk import MskFile

    msk = MskFile.load(path)
    span = (start, end) if start is not None and end is not None else None
    out = draw.cross_section_png(msk, axis, at, _out(output), span=span)
    return {"ok": True, "path": str(out), "axis": axis, "at": at, "span": span}


def simulate_cell(expression: str, out_dir: str, models: str | None = None,
                  vdd: float = 1.2, cload_fF: float = 1.0,
                  delays: bool = True) -> dict:
    """Simulate the compiled netlist with ngspice: truth table, waveforms, delays.

    The netlist is the synthesized transistor list, the models are the vendor cards
    (`spice.lib`), and everything is labelled ngspice - not Microwind's extractor.
    """
    circuit = synthesize(expression)
    out = _out(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = spice.run(circuit, out, _models(models))
    result["truth_table_switch"] = spice.truth_table_switch(circuit)
    result["waveforms_png"] = str(draw.plot_waves(
        result["waves"], circuit.inputs, circuit.name, out / "waveforms.png", result["delays"]))
    if delays:
        result["step_delays"] = spice.measure_delays(
            circuit, out / "steps", _models(models), vdd=vdd, cload=cload_fF * 1e-15)
    result["expression"] = circuit.expression
    result["devices"] = [d.to_dict() for d in circuit.devices]
    return result
