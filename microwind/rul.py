"""Microwind ``.RUL`` technology / design-rule reader.

Format (verified on all 14 shipped rule files, see ``docs/FILE_FORMATS.md``)::

    MICROWIND <version>            plain header line
    NAME <human title>             plain line
    * comment                      star comment
    lambda = 0.05   (comment)      key = value, optional trailing description
    cif metal 23 0.0125            plain line: layer <-> CIF number <-> overetch

Nothing here interprets a rule; it exposes the numbers and the raw text so callers can
decide.  Unknown keys are preserved in ``extra``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*(?:\(([^)]*)\))?$")
# Two shipped syntaxes: `cif metal 23 0.0125` (numeric CIF layer) and the older
# `cif metal METAL1 0.0` (CIF layer *name*).  Both are real, so both parse.
_CIF_RE = re.compile(r"^cif\s+(\w+)\s+(\w+)\s+(-?[\d.]+)\s*$", re.I)
_NUM_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")


@dataclass
class Rule:
    value: str
    comment: str
    raw: str

    @property
    def number(self) -> float | None:
        try:
            return float(self.value)
        except ValueError:
            return None


@dataclass
class Technology:
    path: Path | None = None
    version: str = ""
    name: str = ""
    rules: dict[str, Rule] = field(default_factory=dict)
    cif: dict[str, tuple[int | str, float]] = field(default_factory=dict)
    plain: list[str] = field(default_factory=list)

    # -- convenience ------------------------------------------------------
    @property
    def lam(self) -> float:
        """Microwind lambda in micrometres (half the minimum gate length)."""
        r = self.rules.get("lambda")
        return r.number if r and r.number else 0.0

    @property
    def metal_layers(self) -> int:
        """Metal layer count: declared by `metalLayers`, else counted from `cif`."""
        r = self.rules.get("metalLayers")
        if r is not None and r.number:
            return int(r.number)
        names = [k for k in self.cif if k == "metal" or (k.startswith("metal") and k[5:].isdigit())]
        return max(1, len(names))

    def value(self, key: str, default: float | None = None) -> float | None:
        r = self.rules.get(key)
        if r is None or r.number is None:
            return default
        return r.number

    def gate_length(self) -> float:
        return (self.value("r302") or 0.0) * self.lam

    # -- parsing ----------------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: str | Path | None = None) -> "Technology":
        tech = cls(path=Path(path) if path else None)
        for raw in text.replace("\r\n", "\n").split("\n"):
            line = re.sub(r"//.*$", "", raw).strip()
            if not line or line.startswith("*"):
                continue
            upper = line.upper()
            if upper.startswith("MICROWIND"):
                tech.version = line.split(None, 1)[1] if " " in line else ""
                continue
            if upper.startswith("NAME "):
                tech.name = line[5:].strip()
                continue
            m = _CIF_RE.match(line)
            if m:
                target: int | str = int(m.group(2)) if m.group(2).isdigit() else m.group(2)
                tech.cif[m.group(1).lower()] = (target, float(m.group(3)))
                continue
            m = _KV_RE.match(line)
            if m:
                key = m.group(1)
                tech.rules[key] = Rule(m.group(2).strip(), (m.group(3) or "").strip(), raw)
                continue
            tech.plain.append(line)
        return tech

    @classmethod
    def load(cls, path: str | Path) -> "Technology":
        p = Path(path)
        return cls.parse(p.read_bytes().decode("latin-1"), p)

    def summary(self) -> dict:
        return {
            "file": str(self.path) if self.path else None,
            "version": self.version,
            "name": self.name,
            "lambda_um": self.lam,
            "gate_length_um": round(self.gate_length(), 6),
            "metal_layers": self.metal_layers,
            "rule_count": len(self.rules),
            "cif_layers": sorted(self.cif),
            "switches": {
                k: (self.rules[k].number if self.rules[k].number is not None else self.rules[k].value)
                for k in ("salicide", "edram", "efram", "mimcapa", "strain", "lowK")
                if k in self.rules
            },
            "vdd": self.value("vdd"),
            "temperature": self.value("temperature"),
        }
