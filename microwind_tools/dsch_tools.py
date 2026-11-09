"""DSCH-side tools: parse, inspect and validate schematics, symbols and netlists."""

from __future__ import annotations

from pathlib import Path

from microwind.dsch import DschFile
from microwind.install import find_dsch
from microwind.config import load_config


def _load(path: str | Path) -> DschFile:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"schematic not found: {p}")
    return DschFile.load(p)


def read_schematic(path: str, include_nets: bool = False, limit: int = 100) -> dict:
    """Read a DSCH schematic: components, pins, wires, embedded Verilog and element counts."""
    d = _load(path)
    comps = d.components()
    result = {
        "path": str(Path(path)),
        "dsch_version": d.version,
        "file_timestamp": d.file_version,
        "elements": d.elements(),
        "component_count": len(comps),
        "components": comps[:limit],
        "truncated": len(comps) > limit,
        "texts": d.texts()[:limit],
        "verilog": [line for s in d.symbols for line in s.verilog][:limit],
        "problems": d.validate(),
    }
    if include_nets:
        nets = d.nets()
        result["nets"] = nets[:limit]
        result["net_count"] = len(nets)
    return result


def validate_schematic(path: str) -> dict:
    """Structural validation of a `.sch`/`.sym` file: header, SYM/FSYM balance, pins."""
    d = _load(path)
    problems = d.validate()
    return {
        "path": str(Path(path)),
        "ok": not problems,
        "problems": problems,
        "symbols": len(d.symbols),
        "version": d.version,
    }


def list_symbols(limit: int = 200) -> dict:
    """List the `.sym` user-symbol library that ships with DSCH 3.5."""
    cfg = load_config()
    install = find_dsch(cfg.dsch_home)
    if install is None:
        return {"found": False, "hint": "DSCH not detected; set DSCH_HOME"}
    base = install.examples_dir or install.root
    files = sorted({p.resolve(): p for p in base.rglob("*.sym")}.values(), key=lambda p: p.name.lower())
    out = []
    for path in files[:limit]:
        try:
            d = DschFile.load(path)
            names = [s.name for s in d.symbols]
        except Exception:                                  # noqa: BLE001 - report, don't fail
            names = []
        out.append({"path": str(path), "name": path.stem, "symbols": names[:4]})
    return {"found": True, "count": len(files), "returned": len(out), "symbols": out,
            "truncated": len(files) > limit}


def schematic_netlist(path: str) -> dict:
    """Derive nets from wire geometry: connected pins grouped per net."""
    d = _load(path)
    return {
        "path": str(Path(path)),
        "net_count": len(d.nets()),
        "nets": d.nets()[:200],
    }
