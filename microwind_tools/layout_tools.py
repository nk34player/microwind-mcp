"""Layout-side tools: files, geometry, technology, power grid, CMOS, checks.

Every function is a plain callable with a real implementation; `server.py` only adds
schema/docstring wrappers.  Anything that writes goes through `_write`, which enforces
the configured project roots and makes a backup first.
"""

from __future__ import annotations

from pathlib import Path

from microwind import checks
from microwind.cmos import NETLISTS, build_cell, check_cell
from microwind.config import Config, load_config
from microwind.geometry import bbox as rects_bbox
from microwind.install import detect, find_microwind
from microwind.layers import KNOWN_LAYERS, LayerTable, VIAS, metal_index
from microwind.msk import MskFile
from microwind.power_grid import (
    PowerGridError,
    PowerGridSpec,
    analyze_power_grid as _analyze_grid,
    generate_power_grid as _generate_grid,
    generate_power_rails as _generate_rails,
)
from microwind.rul import Technology
from microwind.safety import SafetyError, ensure_writable, resolve_in_roots

TECH_NAME = "cmos012.rul"


# -- helpers ---------------------------------------------------------------

def _cfg() -> Config:
    return load_config()


def _write(msk: MskFile, path: str | Path) -> dict:
    ensure_writable()
    cfg = _cfg()
    target = resolve_in_roots(path, cfg.roots())
    created = not target.exists()
    msk.path = target
    msk.save(target, make_backup=not created)
    return {"path": str(target), "created": created, "bytes": target.stat().st_size}


def _read(path: str | Path) -> MskFile:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"layout not found: {p}")
    return MskFile.load(p)


def _tech(path: str | Path | None = None) -> Technology | None:
    if path:
        p = Path(path)
        return Technology.load(p) if p.is_file() else None
    mw = find_microwind(_cfg().microwind_home)
    if mw and mw.rules:
        preferred = next((p for p in mw.rules if p.name == TECH_NAME), mw.rules[0])
        return Technology.load(preferred)
    return None


# -- installation / project inventory --------------------------------------

def detect_installation() -> dict:
    """Report the Microwind and DSCH installations that were found on this machine."""
    cfg = _cfg()
    info = detect(cfg.microwind_home, cfg.dsch_home)
    info["project_dirs"] = [str(p) for p in cfg.roots()]
    info["readonly"] = cfg.readonly
    return info


def list_projects(directory: str | None = None, limit: int = 200) -> dict:
    """List `.MSK` / `.sch` files available to the server, with sizes."""
    cfg = _cfg()
    roots = [Path(directory)] if directory else cfg.roots()
    out = []
    for root in roots:
        if not Path(root).is_dir():
            continue
        for sub in ("**/*.MSK", "**/*.msk", "**/*.sch"):
            for path in sorted(Path(root).glob(sub))[:limit]:
                out.append({
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "kind": "layout" if path.suffix.lower() == ".msk" else "schematic",
                })
                if len(out) >= limit:
                    return {"roots": [str(r) for r in roots], "count": len(out), "files": out, "truncated": True}
    return {"roots": [str(r) for r in roots], "count": len(out), "files": out, "truncated": False}


# -- layout files ----------------------------------------------------------

def read_layout(path: str) -> dict:
    """Summarise a layout: dimensions, layers used, labels, bounding box, components."""
    msk = _read(path)
    components = checks.connectivity(msk)
    bb = msk.bbox
    tech = _tech()
    return {
        "path": str(Path(path)),
        "records": len(msk.records),
        "rectangles": len(msk.rects),
        "bbox": list(bb) if bb else None,
        "size_lambda": [bb[2] - bb[0], bb[3] - bb[1]] if bb else None,
        "size_um": [
            round((bb[2] - bb[0]) * tech.lam, 3),
            round((bb[3] - bb[1]) * tech.lam, 3),
        ] if bb and tech and tech.lam else None,
        "layers": msk.layers_used(),
        "labels": [{"text": l.text, "code": l.code, "at": [l.x, l.y]} for l in msk.labels][:100],
        "label_count": len(msk.labels),
        "components": len(components),
        "structure_problems": msk.validate(),
        "header": {
            "version": (msk.header("VERSION").body if msk.header("VERSION") else ""),
            "simu": (msk.header("SIMU").body if msk.header("SIMU") else ""),
            "fig": (msk.header("FIG").body if msk.header("FIG") else ""),
        },
    }


def parse_layout(path: str, limit: int = 200, kind: str | None = None) -> dict:
    """Dump the record stream (keyword + verbatim text), optionally filtered by kind."""
    msk = _read(path)
    records = [
        {"kind": r.kind, "text": r.body}
        for r in msk.records
        if kind is None or r.kind == kind.upper()
    ]
    return {
        "path": str(Path(path)),
        "record_count": len(msk.records),
        "returned": min(len(records), limit),
        "truncated": len(records) > limit,
        "records": records[:limit],
    }


def validate_file(path: str) -> dict:
    """Structural validation of a `.MSK` or `.sch` file (not electrical verification)."""
    p = Path(path)
    if p.suffix.lower() in (".sch", ".sym"):
        from microwind.dsch import DschFile

        d = DschFile.load(p)
        problems = d.validate()
        return {"path": str(p), "kind": "schematic", "ok": not problems, "problems": problems,
                "elements": d.elements(), "symbols": len(d.symbols)}
    msk = _read(path)
    problems = msk.validate()
    return {"path": str(p), "kind": "layout", "ok": not problems, "problems": problems,
            "records": len(msk.records), "rectangles": len(msk.rects)}


def create_layout(path: str, width: int = 200, height: int = 200, tech: str | None = None) -> dict:
    """Create a new empty `.MSK` layout with a valid header."""
    msk = MskFile.new(width, height, path=path)
    result = _write(msk, path)
    return {"layout": read_layout(path), "file": result, "technology": (tech or TECH_NAME)}


def add_rectangle(path: str, x: int, y: int, w: int, h: int, layer: str, extra: int | None = None) -> dict:
    """Add a rectangle to an existing layout (backup taken first)."""
    if layer not in KNOWN_LAYERS:
        raise ValueError(f"unknown layer {layer!r}; see microwind_get_layers")
    msk = _read(path)
    rect = msk.add_rect(x, y, w, h, layer, extra)
    result = _write(msk, path)
    return {"added": {"x": rect.x, "y": rect.y, "w": rect.w, "h": rect.h, "layer": rect.layer},
            "file": result, "rectangles": len(msk.rects)}


def add_label(path: str, x: int, y: int, text: str, code: str = "$-") -> dict:
    """Add a net label (`TITLE` + `$` code) at a point inside existing geometry."""
    msk = _read(path)
    msk.add_label(x, y, text, code)
    result = _write(msk, path)
    return {"label": {"text": text, "code": code, "at": [x, y]}, "file": result,
            "labels": len(msk.labels)}


def modify_layout(
    path: str,
    move: list[dict] | None = None,
    resize: list[dict] | None = None,
    remove: list[dict] | None = None,
) -> dict:
    """Move/resize/remove rectangles by coordinate match. Existing records are preserved."""
    msk = _read(path)
    touched = {"moved": 0, "resized": 0, "removed": 0, "not_found": []}

    def find(x: int, y: int, layer: str | None) -> list:
        return [r for r in msk.rects if r.x == x and r.y == y and (layer is None or r.layer == layer)]

    for spec in move or []:
        for rect in find(spec["x"], spec["y"], spec.get("layer")):
            msk.move(rect, spec.get("dx", 0), spec.get("dy", 0))
            touched["moved"] += 1
        else:
            if not find(spec["x"], spec["y"], spec.get("layer")):
                touched["not_found"].append(spec)
    for spec in resize or []:
        hits = find(spec["x"], spec["y"], spec.get("layer"))
        for rect in hits:
            msk.resize(rect, spec.get("w", rect.w), spec.get("h", rect.h))
            touched["resized"] += 1
        if not hits:
            touched["not_found"].append(spec)
    for spec in remove or []:
        hits = find(spec["x"], spec["y"], spec.get("layer"))
        for rect in hits:
            msk.remove(rect)
            touched["removed"] += 1
        if not hits:
            touched["not_found"].append(spec)

    result = _write(msk, path)
    return {"changes": touched, "file": result, "rectangles": len(msk.rects)}


# -- layers / technology ---------------------------------------------------

def get_layers(tech: str | None = None) -> dict:
    """List every layer code this server can emit or parse, with via pairings."""
    technology = _tech(tech)
    table = LayerTable(technology.cif if technology else None)
    return {
        "layers": table.to_dict(),
        "vias": {k: list(v) for k, v in VIAS.items()},
        "metals": [c for c in KNOWN_LAYERS if metal_index(c)],
        "technology": technology.name if technology else None,
    }


def get_technology(path: str | None = None) -> dict:
    """Return the parsed `.rul`/`.tec` technology: lambda, rules, cif map, models."""
    technology = _tech(path)
    if technology is None:
        return {"found": False, "hint": "set MICROWIND_HOME or pass a path to a .rul file"}
    summary = technology.summary()
    summary["found"] = True
    summary["sample_rules"] = {
        key: technology.value(key)
        for key in ("r201", "r302", "r401", "r501", "r502", "r601")
        if technology.value(key) is not None
    }
    return summary


# -- power grid ------------------------------------------------------------

def generate_power_grid(
    path: str | None = None,
    layers: list[str] | None = None,
    width: int = 200,
    height: int = 200,
    columns: int = 4,
    rows: int = 3,
    wire_width: int = 4,
    rail_widths: dict[str, int] | None = None,
    column_pitch: int | None = None,
    row_pitch: int | None = None,
    margin: int = 0,
    offset: tuple[int, int] = (0, 0),
    voltage_pattern: list[str] | None = None,
    via_size: int = 2,
    via_pad: int = 4,
    label_nets: bool = True,
    check_only: bool = False,
    new_file: str | None = None,
) -> dict:
    """Generate a VDD/VSS power grid on an existing layout, or on a new one."""
    spec = PowerGridSpec(
        layers=layers or ["ME", "M2"],
        width=width,
        height=height,
        columns=columns,
        rows=rows,
        wire_width=wire_width,
        rail_widths=rail_widths or {},
        column_pitch=column_pitch,
        row_pitch=row_pitch,
        margin=margin,
        offset=offset,
        voltage_pattern=voltage_pattern or ["VDD", "VSS"],
        via_size=via_size,
        via_pad=via_pad,
        label_nets=label_nets,
        check_only=check_only,
    )
    if new_file:
        msk = MskFile.new(width, height, path=new_file)
        target = new_file
    else:
        if not path:
            raise ValueError("pass either path (existing layout) or new_file (create one)")
        msk = _read(path)
        target = path
    try:
        report = _generate_grid(msk, spec)
    except PowerGridError as exc:
        return {"ok": False, "error": str(exc), "spec": spec.__dict__}
    if check_only:
        return {"ok": True, "dry_run": True, **report}
    report["file"] = _write(msk, target)
    report["ok"] = True
    return report


def generate_power_rails(
    path: str,
    layer: str = "ME",
    count: int = 4,
    pitch: int = 40,
    length: int = 150,
    width: int = 4,
    vertical: bool = True,
    net: str = "VDD",
    offset: tuple[int, int] = (0, 0),
) -> dict:
    """Generate one bundle of parallel power rails on a single metal layer."""
    msk = _read(path)
    report = _generate_rails(
        msk, layer, count, pitch, length, width, offset=offset, vertical=vertical, net=net
    )
    report["file"] = _write(msk, path)
    report["ok"] = True
    return report


def analyze_power_grid(path: str) -> dict:
    """Summarise existing power rails, VDD/VSS labels and their connected components."""
    return _analyze_grid(_read(path))


# -- CMOS cells ------------------------------------------------------------

def generate_cmos_gate(gate: str, path: str, tech: str | None = None) -> dict:
    """Generate a rule-derived CMOS cell: `inverter`, `nand2` or `nor2`."""
    technology = _tech(tech)
    cell = build_cell(gate, technology, name=Path(path).stem.upper())
    report = check_cell(cell, technology)
    cell.msk.path = Path(path)
    report["file"] = _write(cell.msk, path)
    report["nets"] = cell.to_dict()["nets"]
    return report


# -- verification ----------------------------------------------------------

def run_checks(path: str, tech: str | None = None) -> dict:
    """Run the independent geometric checks (min width, spacing, overlaps, connectivity, power)."""
    msk = _read(path)
    technology = _tech(tech)
    report = checks.run_all(msk, technology)
    report["path"] = str(Path(path))
    return report


def describe_layers_used(path: str) -> dict:
    """Layer histogram plus the technology names for each code found in the file."""
    msk = _read(path)
    used = msk.layers_used()
    return {
        "path": str(Path(path)),
        "layers": [
            {"code": code, "name": KNOWN_LAYERS.get(code, (code, "unknown"))[0], "count": count}
            for code, count in used.items()
        ],
        "unknown_codes": [c for c in used if c not in KNOWN_LAYERS],
    }


def list_gate_types() -> dict:
    """The CMOS cells this build can generate, with their device netlists."""
    return {
        "gates": {
            name: [d.__dict__ for d in devices] for name, devices in NETLISTS.items()
        }
    }
