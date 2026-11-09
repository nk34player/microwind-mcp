"""Loss-preserving reader/writer for DSCH ``.sch`` and ``.sym`` files, plus a
geometric connectivity model.

Format evidence is in ``docs/FILE_FORMATS.md``.  Notes that matter here:

* ``.sch`` uses LF, ``.sym`` uses CRLF — preserved per file.
* Records may wrap across physical lines while parens are unbalanced
  (``Clk24H00.sch``), so records are assembled by paren balance.
* A symbol instance is one ``SYM … FSYM`` block; ``PIN`` and ``LIG`` coordinates inside
  it are absolute drawing coordinates, which is what makes net extraction possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .records import Record, detect_eol, join_records, paren_body, split_records
from .safety import atomic_write, backup, ensure_writable

_PIN_RE = re.compile(r"^(-?\d+)\s*,\s*(-?\d+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)$")
_LIG_RE = re.compile(r"^(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)$")
_BB_RE = re.compile(r"^(-?\d+),(-?\d+),(-?\d+),(-?\d+)$")


@dataclass
class Pin:
    name: str
    x: int
    y: int


@dataclass
class Symbol:
    """One placed symbol instance (a ``SYM … FSYM`` block)."""

    name: str = ""          # "SYM  #16f84"
    label: str = ""         # "TITLE 85 -30  #16f84"
    model: int | None = None
    bbox: tuple[int, int, int, int] | None = None
    pins: list[Pin] = field(default_factory=list)
    wires: list[tuple[int, int, int, int]] = field(default_factory=list)
    verilog: list[str] = field(default_factory=list)
    recs: list[Record] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.name,
            "label": self.label,
            "model": self.model,
            "bbox": list(self.bbox) if self.bbox else None,
            "pins": [{"name": p.name, "x": p.x, "y": p.y} for p in self.pins],
            "verilog": self.verilog,
        }


class DschFile:
    """A parsed DSCH schematic or user symbol."""

    def __init__(self, records: list[Record], eol: str = "\n", path: Path | None = None,
                 final_newline: bool = True):
        self.records = records
        self.eol = eol
        self.path = Path(path) if path else None
        self.final_newline = final_newline

    # -- construction -----------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: str | Path | None = None) -> "DschFile":
        return cls(split_records(text), detect_eol(text), Path(path) if path else None,
                   final_newline=text.endswith(("\n", "\r")))

    @classmethod
    def load(cls, path: str | Path) -> "DschFile":
        p = Path(path)
        return cls.parse(p.read_bytes().decode("latin-1"), p)

    # -- header -----------------------------------------------------------
    @property
    def version(self) -> str:
        rec = self.records[0] if self.records else None
        return rec.body.strip() if rec is not None and rec.kind == "DSCH" else ""

    @property
    def file_version(self) -> str:
        for rec in self.records[:4]:
            if rec.kind == "VERSION":
                return rec.body.strip()[len("VERSION"):].strip()
        return ""

    # -- blocks -----------------------------------------------------------
    @property
    def symbols(self) -> list[Symbol]:
        """All ``SYM … FSYM`` blocks, in file order."""
        out: list[Symbol] = []
        cur: Symbol | None = None
        for rec in self.records:
            if rec.kind == "SYM":
                cur = Symbol()
                cur.recs.append(rec)
                rest = rec.body.strip()[3:].strip()
                cur.name = rest.lstrip("#").strip()
            elif cur is not None:
                cur.recs.append(rec)
                kind = rec.kind
                body = rec.body.strip()
                if kind == "TITLE":
                    cur.label = body.split("#", 1)[1].strip() if "#" in body else ""
                elif kind == "MODEL":
                    try:
                        cur.model = int(body.split()[1])
                    except (IndexError, ValueError):
                        cur.model = None
                elif kind == "BB":
                    inner = paren_body(body)
                    m = _BB_RE.match(re.sub(r"\s+", "", inner or ""))
                    if m:
                        cur.bbox = tuple(int(m.group(i)) for i in range(1, 5))  # type: ignore[assignment]
                elif kind == "PIN":
                    inner = paren_body(body)
                    m = _PIN_RE.match(re.sub(r"\s+", "", inner or ""))
                    if m:
                        name = body[body.rfind(")") + 1:].strip()
                        cur.pins.append(Pin(name, int(m.group(1)), int(m.group(2))))
                elif kind == "LIG":
                    inner = paren_body(body)
                    m = _LIG_RE.match(re.sub(r"\s+", "", inner or ""))
                    if m:
                        cur.wires.append(tuple(int(m.group(i)) for i in range(1, 5)))  # type: ignore[arg-type]
                elif kind == "VLG":
                    cur.verilog.append(rec.body.strip()[3:].strip())
                elif kind == "FSYM":
                    out.append(cur)
                    cur = None
        return out

    def components(self) -> list[dict]:
        return [s.to_dict() for s in self.symbols]

    def texts(self) -> list[str]:
        out = []
        for rec in self.records:
            if rec.kind == "TEXT":
                body = rec.body.strip()
                out.append(body.split("#", 1)[1] if "#" in body else body)
        return out

    def elements(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rec in self.records:
            counts[rec.kind] = counts.get(rec.kind, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    # -- connectivity -----------------------------------------------------
    def nets(self) -> list[dict]:
        """Group pins into nets by wire geometry (endpoint coincidence + on-segment).

        This is a *schematic-level* geometric model: two pins are on the same net when a
        chain of ``LIG`` segments reached from one pin's coordinates reaches the other.
        It deliberately does not know about symbol-internal semantics, which DSCH does
        not export.
        """
        parent: dict[tuple[int, int], tuple[int, int]] = {}

        def find(p):
            parent.setdefault(p, p)
            while parent[p] != p:
                parent[p] = parent[parent[p]]
                p = parent[p]
            return p

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        segments: list[tuple[int, int, int, int]] = []
        points: set[tuple[int, int]] = set()
        for sym in self.symbols:
            for (x1, y1, x2, y2) in sym.wires:
                segments.append((x1, y1, x2, y2))
                points.add((x1, y1))
                points.add((x2, y2))
                union((x1, y1), (x2, y2))
            for pin in sym.pins:
                points.add((pin.x, pin.y))

        # attach pins (and wire endpoints) that lie on another segment
        for (px, py) in points:
            for (x1, y1, x2, y2) in segments:
                if _on_segment(px, py, x1, y1, x2, y2):
                    union((px, py), (x1, y1))

        groups: dict[tuple[int, int], list[dict]] = {}
        for sym in self.symbols:
            for pin in sym.pins:
                root = find((pin.x, pin.y))
                groups.setdefault(root, []).append(
                    {"symbol": sym.name, "pin": pin.name, "x": pin.x, "y": pin.y}
                )
        result = []
        for i, members in enumerate(sorted(groups.values(), key=lambda m: (-len(m), m[0]["symbol"])), 1):
            result.append({"net": f"n{i}", "pin_count": len(members), "pins": members})
        return result

    # -- output -----------------------------------------------------------
    def dumps(self) -> str:
        return join_records(self.records, self.eol, final_eol=self.final_newline)

    def save(self, path: str | Path | None = None, make_backup: bool = True) -> Path:
        ensure_writable()
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no target path")
        if make_backup and target.exists():
            backup(target)
        atomic_write(target, self.dumps())
        self.path = target
        return target

    # -- validation -------------------------------------------------------
    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.records:
            return ["file is empty"]
        if self.records[0].kind != "DSCH":
            problems.append("first record is not DSCH <version>")
        opened = sum(1 for r in self.records if r.kind == "SYM")
        closed = sum(1 for r in self.records if r.kind == "FSYM")
        if opened != closed:
            problems.append(f"{opened} SYM blocks but {closed} FSYM terminators")
        for rec in self.records:
            if rec.kind == "REC" and paren_body(rec.body) is None:
                problems.append(f"malformed REC: {rec.body[:50]}")
        for sym in self.symbols:
            if not sym.name:
                problems.append("symbol block without a name")
            # Duplicate pin names are legitimate: DSCH marks unconnected pins `null`,
            # and a symbol may repeat one several times. Only a pin at the same point
            # with the same name is an error.
            coords = [(p.name, p.x, p.y) for p in sym.pins]
            if len(set(coords)) != len(coords):
                problems.append(f"symbol {sym.name}: duplicate pin at identical coordinates")
        return problems


def _on_segment(px: int, py: int, x1: int, y1: int, x2: int, y2: int) -> bool:
    cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    if cross != 0:
        return False
    return min(x1, x2) <= px <= max(x1, x2) and min(y1, y2) <= py <= max(y1, y2)
