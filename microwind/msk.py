"""Loss-preserving reader/writer for Microwind ``.MSK`` layouts.

Format evidence lives in ``docs/FILE_FORMATS.md``.  In short: a flat text file with a
fixed header, then geometry records, then a footer.  Records this module does not model
are kept verbatim so that unknown declarations survive a read/modify/write cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .records import Record, detect_eol, join_records, paren_body, split_records
from .safety import atomic_write, backup, ensure_writable

REC_LAYER_RE = re.compile(r"^(-?\d+),(-?\d+),(-?\d+),(-?\d+),([A-Za-z][A-Za-z0-9]*)(?:,(-?\d+))?$")
TITLE_RE = re.compile(r"^(-?\d+)\s+(-?\d+)\s+#(.*)$")

#: bounding-box / viewport header records
BB_KINDS = {"BB", "ZOOM"}


class MskError(ValueError):
    pass


def stamp(dt: datetime | None = None) -> str:
    """Microwind's ``M/D/YYYY H:MM:SS AM/PM`` timestamp."""
    d = dt or datetime.now()
    hour = d.hour % 12 or 12
    return f"{d.month}/{d.day}/{d.year} {hour}:{d.minute:02d}:{d.second:02d} {'AM' if d.hour < 12 else 'PM'}"


@dataclass
class Label:
    x: int
    y: int
    text: str
    code: str = "$-"
    args: tuple[str, ...] = ("1000", "0")
    raw_code: str = ""


class Rect(Record):
    """A ``REC(x, y, w, h, LAYER[, VALUE])`` record, mutable."""

    __slots__ = ("x", "y", "w", "h", "layer", "extra", "dirty")

    def __init__(self, raw: str, x: int, y: int, w: int, h: int, layer: str, extra: int | None = None):
        super().__init__("REC", raw)
        self.x, self.y, self.w, self.h = x, y, w, h
        self.layer = layer
        self.extra = extra
        self.dirty = False

    @classmethod
    def parse(cls, raw: str) -> "Rect | None":
        body = paren_body(raw)
        if body is None:
            return None
        inner = re.sub(r"\s+", "", body)
        m = REC_LAYER_RE.match(inner)
        if not m:
            return None
        x, y, w, h = (int(m.group(i)) for i in range(1, 5))
        extra = int(m.group(6)) if m.group(6) is not None else None
        return cls(raw, x, y, w, h, m.group(5), extra)

    @classmethod
    def make(cls, x: int, y: int, w: int, h: int, layer: str, extra: int | None = None) -> "Rect":
        r = cls("", x, y, w, h, layer, extra)
        r.dirty = True
        return r

    # -- geometry helpers -------------------------------------------------
    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return self.w * self.h

    def overlaps(self, o: "Rect") -> bool:
        """True when the two rectangles share positive area (touching is not overlap)."""
        return (
            self.x < o.x2 and o.x < self.x2 and self.y < o.y2 and o.y < self.y2
        )

    def overlaps_area(self, o: "Rect") -> int:
        dx = min(self.x2, o.x2) - max(self.x, o.x)
        dy = min(self.y2, o.y2) - max(self.y, o.y)
        return dx * dy if dx > 0 and dy > 0 else 0

    def touches(self, o: "Rect") -> bool:
        """True when the rectangles overlap or share an edge."""
        return (
            self.x <= o.x2 and o.x <= self.x2 and self.y <= o.y2 and o.y <= self.y2
        )

    def to_line(self) -> str:
        extra = f",{self.extra}" if self.extra is not None else ""
        return f"REC({self.x},{self.y},{self.w},{self.h},{self.layer}{extra})"

    def __repr__(self) -> str:
        return f"Rect({self.x},{self.y},{self.w},{self.h},{self.layer})"


class MskFile:
    """A parsed ``.MSK`` layout."""

    def __init__(self, records: list[Record], eol: str = "\r\n", path: Path | None = None,
                 final_newline: bool = True):
        self.records = records
        self.eol = eol
        self.path = Path(path) if path else None
        self.final_newline = final_newline

    # -- construction -----------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: str | Path | None = None) -> "MskFile":
        records = split_records(text)
        for i, rec in enumerate(records):
            if rec.kind == "REC":
                rect = Rect.parse(rec.raw)
                if rect is not None:
                    rect.raw = rec.raw
                    rect.dirty = False
                    records[i] = rect
        return cls(records, detect_eol(text), Path(path) if path else None,
                   final_newline=text.endswith(("\n", "\r")))

    @classmethod
    def load(cls, path: str | Path) -> "MskFile":
        p = Path(path)
        return cls.parse(p.read_bytes().decode("latin-1"), p)

    @classmethod
    def new(
        cls,
        width: int = 100,
        height: int = 100,
        path: str | Path = "UNTITLED.MSK",
        simu: str = "2.50",
        zoom: tuple[int, int, int, int] = (-25, -20, 55, 55),
    ) -> "MskFile":
        p = str(Path(path))
        head = [
            f"VERSION {stamp()}",
            f"FIG #{p}",
            f"BB(0,0,{width},{height})",
            f"SIMU #{simu}",
            f"ZOOM({zoom[0]},{zoom[1]},{zoom[2]},{zoom[3]})",
        ]
        records = [Record(_kind_of(line), line + "\r\n") for line in head]
        records.append(Record("FFIG", f"FFIG {p}\r\n"))
        return cls(records, "\r\n", Path(path))

    # -- views ------------------------------------------------------------
    @property
    def rects(self) -> list[Rect]:
        return [r for r in self.records if isinstance(r, Rect)]

    def header(self, kind: str) -> Record | None:
        for rec in self.records:
            if rec.kind == kind:
                return rec
        return None

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        rects = self.rects
        if not rects:
            return None
        return (
            min(r.x for r in rects),
            min(r.y for r in rects),
            max(r.x2 for r in rects),
            max(r.y2 for r in rects),
        )

    @property
    def labels(self) -> list[Label]:
        out: list[Label] = []
        recs = self.records
        for i, rec in enumerate(recs):
            if rec.kind != "TITLE":
                continue
            m = TITLE_RE.match(rec.body.strip()[len("TITLE"):].strip())
            if not m:
                continue
            code, args, raw_code = "$-", ("1000", "0"), ""
            if i + 1 < len(recs) and recs[i + 1].kind:
                nxt = recs[i + 1].body.strip()
                if nxt.startswith("$"):
                    parts = nxt.split()
                    code, args, raw_code = parts[0], tuple(parts[1:]), nxt
            out.append(Label(int(m.group(1)), int(m.group(2)), m.group(3).strip(), code, args, raw_code))
        return out

    def layers_used(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.rects:
            counts[r.layer] = counts.get(r.layer, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    # -- mutation ---------------------------------------------------------
    def add(self, rect: Rect) -> Rect:
        """Append a rectangle (before the footer if one exists)."""
        rect.dirty = True
        idx = next((i for i, r in enumerate(self.records) if r.kind == "FFIG"), len(self.records))
        self.records.insert(idx, rect)
        return rect

    def add_rect(self, x: int, y: int, w: int, h: int, layer: str, extra: int | None = None) -> Rect:
        return self.add(Rect.make(x, y, w, h, layer, extra))

    def add_label(self, x: int, y: int, text: str, code: str = "$-", args: tuple[str, ...] = ("1000", "0")) -> None:
        title = Record("TITLE", f"TITLE {x} {y}  #{text}")
        codeline = Record("$", f"{code} {' '.join(args)}") if code else Record("$", "$- 1000 0")
        idx = next((i for i, r in enumerate(self.records) if r.kind == "FFIG"), len(self.records))
        self.records[idx:idx] = [title, codeline]

    def remove(self, rect: Rect) -> None:
        self.records = [r for r in self.records if r is not rect]

    def move(self, rect: Rect, dx: int, dy: int) -> Rect:
        rect.x += dx
        rect.y += dy
        rect.dirty = True
        return rect

    def resize(self, rect: Rect, w: int, h: int) -> Rect:
        if w < 0 or h < 0:
            raise MskError("rectangle size must be non-negative")
        rect.w, rect.h = w, h
        rect.dirty = True
        return rect

    # -- output -----------------------------------------------------------
    def dumps(self, recompute_bbox: bool | None = None) -> str:
        if recompute_bbox is None:
            recompute_bbox = any(r.dirty for r in self.rects)
        for rec in self.records:
            if isinstance(rec, Rect) and rec.dirty:
                rec.raw = rec.to_line()
                rec.dirty = False
        if recompute_bbox:
            bb = self.bbox
            if bb is not None:
                rec = self.header("BB")
                if rec is not None:
                    rec.raw = f"BB({bb[0]},{bb[1]},{bb[2]},{bb[3]})"
        return join_records(self.records, self.eol, final_eol=self.final_newline)

    def save(self, path: str | Path | None = None, make_backup: bool = True) -> Path:
        ensure_writable()
        target = Path(path) if path else self.path
        if target is None:
            raise MskError("no target path: pass one or set .path")
        if make_backup and target.exists():
            backup(target)
        atomic_write(target, self.dumps())
        self.path = target
        return target

    # -- validation -------------------------------------------------------
    def validate(self) -> list[str]:
        """Structural (not electrical) validation of the record stream."""
        problems: list[str] = []
        kinds = {r.kind for r in self.records}
        for required in ("VERSION", "FIG", "BB", "SIMU", "FFIG"):
            if required not in kinds:
                problems.append(f"missing required header record {required}")
        if self.records and self.records[-1].kind != "FFIG":
            problems.append("file does not end with FFIG")
        for rec in self.records:
            if rec.kind == "REC" and not isinstance(rec, Rect):
                problems.append(f"malformed rectangle: {rec.body[:60]}")
        bb = self.header("BB")
        geo = self.bbox
        if bb is not None and geo is not None:
            m = re.match(r"^BB\((-?\d+),(-?\d+),(-?\d+),(-?\d+)\)$", bb.body.strip())
            if not m:
                problems.append("malformed BB record")
            else:
                got = tuple(int(m.group(i)) for i in range(1, 5))
                # Verified on all 275 non-empty fixtures: BB always *contains* the
                # geometry union, and is a strict superset in 164 of them. Equality
                # is therefore not a rule; containment is.
                if not (got[0] <= geo[0] and got[1] <= geo[1] and got[2] >= geo[2] and got[3] >= geo[3]):
                    problems.append(f"BB {got} does not contain geometry {geo}")
        for rec in self.rects:
            if rec.w < 0 or rec.h < 0:
                problems.append(f"negative rectangle size at {rec.x},{rec.y}")
        return problems


def _kind_of(line: str) -> str:
    m = re.match(r"^([A-Za-z][A-Za-z0-9]*)", line.strip())
    return m.group(1) if m else ""
