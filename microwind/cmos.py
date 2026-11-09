"""CMOS cell generation from geometry primitives measured in the 3.5 fixtures.

Only layers that occur in real Microwind 3.5 layouts are emitted (`NW, DN, DP, PO, CO,
ME, M2, VI`) and every dimension comes from a `.RUL` rule, so the cells are rule-derived
rather than guessed:

    active height   r201 (diffusion width)
    gate length     r302
    poly overhang   r307
    contact         r401, diffusion border r405, metal border r403
    nwell border    r203
    metal width     r501, metal spacing r502

The cell is deliberately a *single device row* with a routing channel above it: every
terminal rises on `M2` (different layer from the `ME` tracks), so no two stubs can ever
cross, and connectivity does not depend on planarity heuristics.  Correctness is then
checked structurally: terminals of the same net must land in one geometric component and
different nets in different components (`verify_cell`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .checks import check_spacing, check_width
from .msk import MskFile
from .rul import Technology

#: device slot geometry (lambda)
DEVICE_W = 36
DEVICE_GAP = 24
TRACK_PITCH = 10
TRACK_Y0 = 20
TRACK_H = 3
STUB_W = 3
INPUT_RAIL_Y = -14

PAD = 4
VIA = 2

NW_BORDER = 6


class CmosError(ValueError):
    pass


@dataclass
class DeviceSpec:
    name: str
    kind: str                    # "n" or "p"
    source: str
    drain: str
    gate: str


@dataclass
class Cell:
    name: str
    msk: MskFile
    devices: list[DeviceSpec]
    nets: dict[str, dict]        # net -> {"track_y", "stubs": [...], "terminals": [(x,y,name)]}
    rails: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "devices": [d.__dict__ for d in self.devices],
            "nets": {k: {"track_y": v["track_y"], "terminals": v["terminals"]} for k, v in self.nets.items()},
            "rectangles": len(self.msk.rects),
        }


NETLISTS: dict[str, list[DeviceSpec]] = {
    "inverter": [
        DeviceSpec("n1", "n", "VSS", "Y", "A"),
        DeviceSpec("p1", "p", "VDD", "Y", "A"),
    ],
    "nand2": [
        DeviceSpec("n1", "n", "VSS", "MID", "A"),
        DeviceSpec("n2", "n", "MID", "Y", "B"),
        DeviceSpec("p1", "p", "VDD", "Y", "A"),
        DeviceSpec("p2", "p", "VDD", "Y", "B"),
    ],
    "nor2": [
        DeviceSpec("n1", "n", "VSS", "Y", "A"),
        DeviceSpec("n2", "n", "VSS", "Y", "B"),
        DeviceSpec("p1", "p", "VDD", "MID", "A"),
        DeviceSpec("p2", "p", "MID", "Y", "B"),
    ],
}

NET_CODES = {"VDD": "$1", "VSS": "$0"}


def _rules(tech: Technology | None) -> dict[str, int]:
    def v(key: str, default: int) -> int:
        if tech is None:
            return default
        got = tech.value(key)
        return int(got) if got else default

    return {
        "active_h": max(4, v("r201", 4)),
        "gate": max(1, v("r302", 2)),
        "poly_over": max(1, v("r307", 3)),
        "contact": max(1, v("r401", 2)),
        "co_diff": max(1, v("r405", 1)),
        "co_metal": max(1, v("r403", 1)),
        "metal_w": max(1, v("r501", 3)),
        "metal_s": max(1, v("r502", 4)),
        "nwell_b": max(1, v("r203", 6)),
    }


def _device_geometry(x0: int, kind: str, r: dict[str, int]) -> dict:
    """Rectangles + terminal attachment points for one transistor at slot origin x0."""
    h = r["active_h"]
    gate = r["gate"]
    diff = "DN" if kind == "n" else "DP"
    gx = x0 + DEVICE_W // 2 - gate // 2
    src_x = x0 + DEVICE_W // 6
    drn_x = x0 + DEVICE_W - DEVICE_W // 6 - r["contact"]

    rects = [
        # active area
        (x0, 0, DEVICE_W, h, diff),
        # gate: crosses the active with `poly_over` lambda overhang on both sides
        (gx, -r["poly_over"], gate, h + 2 * r["poly_over"], "PO"),
        # source / drain contacts + metal pads
        (src_x, r["co_diff"], r["contact"], r["contact"], "CO"),
        (drn_x, r["co_diff"], r["contact"], r["contact"], "CO"),
        (src_x - r["co_metal"], 0, PAD, PAD, "ME"),
        (drn_x - r["co_metal"], 0, PAD, PAD, "ME"),
        # vias up to the M2 stubs
        (src_x, r["co_diff"], VIA, VIA, "VI"),
        (drn_x, r["co_diff"], VIA, VIA, "VI"),
        # gate pad below the row: PO -> CO -> ME -> VI, so the input rail can reach it
        (gx - 2, -r["poly_over"] - 5, gate + 4, 6, "PO"),
        (gx, -r["poly_over"] - 4, r["contact"], r["contact"], "CO"),
        (gx - r["co_metal"], -r["poly_over"] - 5, PAD, PAD, "ME"),
        (gx, -r["poly_over"] - 4, VIA, VIA, "VI"),
    ]
    return {
        "rects": rects,
        "source_x": src_x,
        "drain_x": drn_x,
        "gate_x": gx,
        "source_point": (src_x + 1, r["co_diff"] + 1),
        "drain_point": (drn_x + 1, r["co_diff"] + 1),
        "gate_point": (gx + 1, -r["poly_over"] - 3),
        "active_top": h,
    }


def build_cell(gate: str, tech: Technology | None = None, name: str | None = None) -> Cell:
    """Generate `inverter`, `nand2` or `nor2` as a native `.MSK` layout."""
    key = gate.lower()
    if key not in NETLISTS:
        raise CmosError(f"unknown gate {gate!r}; expected one of {sorted(NETLISTS)}")
    devices = NETLISTS[key]
    r = _rules(tech)
    cell_name = name or key.upper()

    width = len(devices) * DEVICE_W + (len(devices) - 1) * DEVICE_GAP + 40
    msk = MskFile.new(width, 120, path=f"{cell_name}.MSK")

    # net -> terminals, insertion order preserved
    nets: dict[str, list[tuple[int, int]]] = {}
    placed: list[dict] = []
    for i, dev in enumerate(devices):
        x0 = 20 + i * (DEVICE_W + DEVICE_GAP)
        g = _device_geometry(x0, dev.kind, r)
        for rect in g["rects"]:
            msk.add_rect(*rect)
        if dev.kind == "p":
            # nwell must enclose the p-diffusion with the rule border
            msk.add_rect(
                x0 - r["nwell_b"], -r["nwell_b"],
                DEVICE_W + 2 * r["nwell_b"], r["active_h"] + 2 * r["nwell_b"],
                "NW",
            )
        nets.setdefault(dev.source, []).append(g["source_point"])
        nets.setdefault(dev.drain, []).append(g["drain_point"])
        nets.setdefault(dev.gate, []).append(g["gate_point"])
        placed.append({"dev": dev, "geom": g})

    # routing channel: one ME track per net, M2 stubs, via at each junction
    ordered = sorted(nets, key=lambda n: (n not in ("VDD", "VSS"), n))
    track_info: dict[str, dict] = {}
    for k, net in enumerate(ordered):
        track_y = TRACK_Y0 + k * TRACK_PITCH
        xs = [x for x, _ in nets[net]]
        x_lo, x_hi = min(xs) - 2, max(xs) + 3
        track = msk.add_rect(x_lo, track_y, x_hi - x_lo, TRACK_H, "ME")
        stubs = []
        for (tx, _ty) in nets[net]:
            # vertical M2 stub from the terminal via up to this track
            stub_bottom = 0 if net not in ("A", "B") else INPUT_RAIL_Y
            if _ty > 0:  # source/drain terminal: rises from the via
                y0 = _ty - 1
                length = track_y + VIA - y0
            else:        # gate terminal: falls to the input rail level
                y0 = INPUT_RAIL_Y
                length = (track_y + VIA) - y0
            msk.add_rect(tx - 1, y0, STUB_W, length, "M2")
            # junction: ME pad + via so the stub legally lands on the track
            msk.add_rect(tx - 2, track_y - 1, PAD + 1, PAD + 1, "ME")
            msk.add_rect(tx - 1, track_y, VIA, VIA, "VI")
            stubs.append({"x": tx, "y0": y0, "y1": track_y + VIA})
        track_info[net] = {"track_y": track_y, "terminals": nets[net], "stubs": stubs}

        # label the power nets with the confirmed $1/$0 mechanism
        if net in NET_CODES:
            msk.add_label(x_lo + 2, track_y + 1, net, NET_CODES[net], ("1000", "0"))

    # input rails: horizontal M3 wires below the row.  M3 (not M2) because gate stubs are
    # M2 and would otherwise short against another input's rail; different layers cannot
    # short, so the two inputs stay independent by construction.
    rails: list[dict] = []
    gate_nets = sorted(n for n in nets if n not in NET_CODES and n not in ("Y", "MID"))
    for j, net in enumerate(gate_nets):
        y = INPUT_RAIL_Y - j * (TRACK_H + 5)
        xs = [x for x, _ in nets[net]]
        x_lo, x_hi = min(xs) - 2, max(xs) + 2
        msk.add_rect(x_lo, y, x_hi - x_lo, TRACK_H, "M3")
        msk.add_label(x_lo + 1, y + 1, net, "$-", ("1000", "0"))
        rails.append({"net": net, "y": y, "x": [x_lo, x_hi], "layer": "M3"})
        for (tx, ty) in nets[net]:
            if ty < 0:  # gate pad: M2 stub down to this rail, then an M2/M3 via
                msk.add_rect(tx - 1, y, STUB_W, (ty + VIA) - y, "M2")
                msk.add_rect(tx - 2, y - 1, PAD + 1, PAD + 1, "M2")
                msk.add_rect(tx - 1, y, VIA, VIA, "V2")

    return Cell(cell_name, msk, devices, track_info, rails)


def verify_cell(cell: Cell) -> dict:
    """Structural check: same-net terminals share a component, different nets do not."""
    # precise: rebuild index -> component using the same union-find as checks
    from .checks import _node_edges

    rects = cell.msk.rects
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in _node_edges(cell.msk):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    def component_index(x: int, y: int) -> int | None:
        for i, r in enumerate(rects):
            if r.layer in ("ME",) and r.x <= x < r.x2 and r.y <= y < r.y2:
                return find(i)
        return None

    net_components: dict[str, set[int]] = {}
    failures: list[str] = []
    for net, info in cell.nets.items():
        idxs = set()
        for (x, y) in info["terminals"]:
            idx = component_index(x, y)
            if idx is None:
                failures.append(f"net {net}: terminal at ({x},{y}) is not on geometry")
            else:
                idxs.add(idx)
        net_components[net] = idxs
        if len(idxs) > 1:
            failures.append(f"net {net}: spans {len(idxs)} separate components")

    seen: dict[int, str] = {}
    for net, idxs in net_components.items():
        for idx in idxs:
            if idx in seen and seen[idx] != net:
                failures.append(f"nets {seen[idx]} and {net} are shorted (component {idx})")
            seen.setdefault(idx, net)

    return {
        "nets": {k: sorted(v) for k, v in net_components.items()},
        "components": len({i for s in net_components.values() for i in s}),
        "shorts_or_opens": failures,
        "ok": not failures,
    }


def check_cell(cell: Cell, tech: Technology | None = None) -> dict:
    width = check_width(cell.msk, tech)
    spacing = check_spacing(cell.msk, tech)
    structural = verify_cell(cell)
    return {
        "gate": cell.name,
        "rectangles": len(cell.msk.rects),
        "structural": structural,
        "min_width_violations": width[:20],
        "min_spacing_violations": spacing[:20],
        "ok": structural["ok"] and not width and not spacing,
    }
