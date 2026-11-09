"""Layer codes, metal stacks and via mapping for Microwind 3.5.

The authoritative layer→CIF correspondence lives in the `.RUL` files (`cif` lines); this
module supplies the *semantics* that the `.rul` does not encode (which code is metal N,
which code is the via between two metals).  Codes not listed here still round-trip: the
table is used for validation and generation, never for filtering parsed geometry.
"""

from __future__ import annotations

from dataclasses import dataclass

#: code -> (human name, kind)  — measured against the 3.5 example set
KNOWN_LAYERS: dict[str, tuple[str, str]] = {
    "NW": ("nwell", "well"),
    "DN": ("diffn", "diffusion"),
    "DP": ("diffp", "diffusion"),
    "PO": ("poly", "gate"),
    "CO": ("contact", "contact"),
    "ME": ("metal1", "metal"),
    "M2": ("metal2", "metal"),
    "M3": ("metal3", "metal"),
    "M4": ("metal4", "metal"),
    "M5": ("metal5", "metal"),
    "M6": ("metal6", "metal"),
    "M7": ("metal7", "metal"),
    "M8": ("metal8", "metal"),
    "VI": ("via1", "via"),
    "V2": ("via2", "via"),
    "V3": ("via3", "via"),
    "V4": ("via4", "via"),
    "V5": ("via5", "via"),
    "V6": ("via6", "via"),
    "V7": ("via7", "via"),
    "PA": ("passivation", "passivation"),
    "P2": ("poly2", "capacitor"),
    "OP": ("overlay", "device"),
}

#: metal stack in order; index >= 1 in `METALS`
METALS: tuple[str, ...] = ("ME", "M2", "M3", "M4", "M5", "M6", "M7", "M8")

#: via code -> (lower metal, upper metal)  — matches the `.rul` cif ordering
VIAS: dict[str, tuple[str, str]] = {
    "VI": ("ME", "M2"),
    "V2": ("M2", "M3"),
    "V3": ("M3", "M4"),
    "V4": ("M4", "M5"),
    "V5": ("M5", "M6"),
    "V6": ("M6", "M7"),
    "V7": ("M7", "M8"),
}

#: rule-key pairs per layer: (min width, min spacing) as they appear in `.rul` files.
#: Keys absent from a technology file mean "no independent check", never "zero rule".
RULE_KEYS: dict[str, tuple[str, str]] = {
    "NW": ("r101", "r102"),
    "DN": ("r201", "r202"),
    "DP": ("r201", "r202"),
    "PO": ("r301", "r304"),
    "CO": ("r401", "r402"),
    "ME": ("r501", "r502"),
    "M2": ("r701", "r702"),
    "M3": ("r901", "r902"),
    "M4": ("rb01", "rb02"),
    "M5": ("rd01", "rd02"),
    "M6": ("rf01", "rf02"),
    "VI": ("r601", "r602"),
    "V2": ("r801", "r802"),
    "V3": ("ra01", "ra02"),
    "V4": ("rc01", "rc02"),
    "V5": ("re01", "re02"),
}

#: minimum legal via unit measured from the fixtures: 2λ via in a 4λ pad
VIA_SIZE = 2
VIA_PAD = 4
VIA_ENCLOSURE = (VIA_PAD - VIA_SIZE) // 2

#: `$` net codes with a confirmed electrical meaning
POWER_CODES = {"$1": "VDD", "$0": "VSS"}


def is_metal(code: str) -> bool:
    return KNOWN_LAYERS.get(code, ("", ""))[1] == "metal"


def is_via(code: str) -> bool:
    return code in VIAS


def metal_index(code: str) -> int | None:
    return METALS.index(code) + 1 if code in METALS else None


def via_between(a: str, b: str) -> str | None:
    """Return the via code connecting metals `a` and `b` (order-insensitive)."""
    for code, pair in VIAS.items():
        if {pair[0], pair[1]} == {a, b}:
            return code
    return None


def describe(code: str) -> str:
    name, kind = KNOWN_LAYERS.get(code, (code, "unknown"))
    return f"{name} ({kind})"


@dataclass(frozen=True)
class LayerInfo:
    code: str
    name: str
    kind: str


class LayerTable:
    """Known codes merged with a technology's `cif` map."""

    def __init__(self, cif: dict[str, tuple[int, float]] | None = None):
        self.cif = cif or {}

    def is_known(self, code: str) -> bool:
        return code in KNOWN_LAYERS or code.lower() in self.cif

    def unknown(self, codes) -> list[str]:
        return sorted({c for c in codes if not self.is_known(c)})

    def to_dict(self) -> list[dict]:
        out = []
        for code, (name, kind) in KNOWN_LAYERS.items():
            entry: dict = {"code": code, "name": name, "kind": kind}
            if is_metal(code):
                entry["metal_index"] = metal_index(code)
            if code in VIAS:
                entry["connects"] = list(VIAS[code])
            cif = self.cif.get(name.lower()) or self.cif.get(code.lower())
            if cif:
                entry["cif"] = {"layer": cif[0], "overetch_um": cif[1]}
            out.append(entry)
        return out
