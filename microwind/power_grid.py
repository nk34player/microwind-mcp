"""Parametric power-grid generation for Microwind `.MSK`.

Design ideas from ``OdaiJ/microwind-power-grid-generator`` (no license declared, so this
is an independent implementation):
  * metal layers alternate orientation — odd index vertical columns, even horizontal rows
  * a repeating voltage pattern assigns VDD/VSS to stripes on both axes
  * a via is placed only where both crossing rails carry the same supply

Independent decisions on top of that:
  * every rectangle goes through the normal `MskFile.add_rect` path, so the writer keeps
    all existing records untouched
  * collisions against existing geometry are detected *before* insertion and reported
  * the minimum via unit is the measured one: 2λ via inside a 4λ pad on both metals
  * labels use the confirmed `TITLE` + `$1`/`$0` mechanism
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import overlap_area
from .layers import METALS, VIA_ENCLOSURE, VIA_SIZE, VIAS, via_between
from .msk import MskFile, Rect

POWER_CODES = {"VDD": "$1", "VSS": "$0", "VDD_hv": "$1"}
FLOAT = "FLOAT"


class PowerGridError(ValueError):
    pass


@dataclass
class PowerGridSpec:
    """Everything needed to build a grid. Defaults target a small 0.12µm-style cell."""

    layers: list[str] = field(default_factory=lambda: ["ME", "M2"])
    width: int = 200                 # grid extent in lambda (x)
    height: int = 200                # grid extent in lambda (y)
    columns: int = 4                 # stripes on vertical layers
    rows: int = 3                    # stripes on horizontal layers
    column_pitch: int | None = None  # centre-to-centre; derived from the extent if None
    row_pitch: int | None = None
    rail_widths: dict[str, int] = field(default_factory=dict)  # per layer, default `wire_width`
    wire_width: int = 4
    offset: tuple[int, int] = (0, 0)
    margin: int = 0
    voltage_pattern: list[str] = field(default_factory=lambda: ["VDD", "VSS"])
    via_size: int = VIA_SIZE
    via_pad: int = 4
    vdd_name: str = "VDD"
    vss_name: str = "VSS"
    label_nets: bool = True
    check_only: bool = False
    auto_place: bool = True      # on collision, shift the grid right of existing geometry

    # -- validation -------------------------------------------------------
    def validate(self) -> None:
        if not self.layers:
            raise PowerGridError("layers must not be empty")
        for layer in self.layers:
            if layer not in METALS:
                raise PowerGridError(f"unknown metal layer {layer!r}; expected one of {METALS}")
        if self.columns < 1 or self.rows < 1:
            raise PowerGridError("columns and rows must be >= 1")
        if self.wire_width < 1:
            raise PowerGridError("wire_width must be >= 1")
        if min(self.width, self.height) < 1:
            raise PowerGridError("grid width and height must be positive")
        if not self.voltage_pattern:
            raise PowerGridError("voltage_pattern must not be empty")
        bad = [v for v in self.voltage_pattern if v not in (self.vdd_name, self.vss_name, FLOAT)]
        if bad:
            raise PowerGridError(f"voltage_pattern entries must be {self.vdd_name}/{self.vss_name}/{FLOAT}, got {bad}")
        if self.via_pad < self.via_size + 2 * VIA_ENCLOSURE:
            raise PowerGridError(
                f"via_pad {self.via_pad} gives less than {VIA_ENCLOSURE}λ enclosure around a {self.via_size}λ via"
            )

    def width_for(self, layer: str) -> int:
        return int(self.rail_widths.get(layer, self.wire_width))


def _stripe_positions(count: int, pitch: int | None, extent: int, margin: int, width: int) -> tuple[list[int], int]:
    """Lower-left coordinates of `count` stripes plus the pitch actually used."""
    usable = max(1, extent - 2 * margin)
    if pitch is None:
        pitch = usable // count if count > 1 else usable
    pitch = max(pitch, width)
    return [margin + i * pitch for i in range(count)], pitch


def _collisions(planned: list[tuple[Rect, str]], existing_rects: list[Rect]) -> list[dict]:
    out: list[dict] = []
    for rect, _net in planned:
        for existing in existing_rects:
            if existing.layer != rect.layer:
                continue
            if rect.overlaps(existing) and not (
                (rect.x, rect.y, rect.w, rect.h) == (existing.x, existing.y, existing.w, existing.h)
            ):
                out.append({
                    "layer": rect.layer,
                    "new": [rect.x, rect.y, rect.w, rect.h],
                    "existing": [existing.x, existing.y, existing.w, existing.h],
                    "area": overlap_area(rect, existing),
                })
    return out


def generate_power_grid(msk: MskFile, spec: PowerGridSpec) -> dict:
    """Add a power grid to `msk` in place (or only report, when ``spec.check_only``)."""
    spec.validate()
    before = list(msk.rects)
    ox, oy = spec.offset
    pattern = spec.voltage_pattern

    # 1. plan the rails ---------------------------------------------------
    planned: list[tuple[Rect, str]] = []       # (rect, net)
    vertical_layers = [l for i, l in enumerate(spec.layers) if i % 2 == 0]
    horizontal_layers = [l for i, l in enumerate(spec.layers) if i % 2 == 1]

    for layer in vertical_layers:
        w = spec.width_for(layer)
        xs, pitch = _stripe_positions(spec.columns, spec.column_pitch, spec.width, spec.margin, w)
        for k, x in enumerate(xs):
            rect = Rect.make(ox + x, oy + spec.margin, w, spec.height - 2 * spec.margin, layer)
            planned.append((rect, pattern[k % len(pattern)]))

    for layer in horizontal_layers:
        w = spec.width_for(layer)
        ys, pitch = _stripe_positions(spec.rows, spec.row_pitch, spec.height, spec.margin, w)
        for k, y in enumerate(ys):
            rect = Rect.make(ox + spec.margin, oy + y, spec.width - 2 * spec.margin, w, layer)
            planned.append((rect, pattern[k % len(pattern)]))

    if not planned:
        raise PowerGridError("layers must contain at least one metal layer")

    # 2. collision detection against existing geometry -------------------
    collisions = _collisions(planned, before)
    if collisions and spec.auto_place and before:
        # Same behaviour as Microwind's own cell compiler: move the new block to the
        # right of the occupied area instead of overwriting it.
        shift = max(r.x2 for r in before) + spec.margin - min(r.x for r, _ in planned)
        for rect, _net in planned:
            rect.x += shift
        collisions = _collisions(planned, before)

    # 3. via plan at same-supply crossings --------------------------------
    vias: list[Rect] = []
    via_pairs: list[dict] = []
    for i, (a, net_a) in enumerate(planned):
        if net_a == FLOAT:
            continue
        for b, net_b in planned[i + 1:]:
            if net_b != net_a:
                continue
            if not a.overlaps(b):
                continue
            low, high = _order_by_stack(a.layer, b.layer)
            if low is None:
                continue
            via_code = via_between(low, high)
            if via_code is None:
                continue
            # centre of the overlap region
            cx = (max(a.x, b.x) + min(a.x2, b.x2)) // 2
            cy = (max(a.y, b.y) + min(a.y2, b.y2)) // 2
            half = spec.via_pad // 2
            pad_low = Rect.make(cx - half, cy - half, spec.via_pad, spec.via_pad, low)
            pad_high = Rect.make(cx - half, cy - half, spec.via_pad, spec.via_pad, high)
            via_size = spec.via_size
            off = (spec.via_pad - via_size) // 2
            via = Rect.make(cx - half + off, cy - half + off, via_size, via_size, via_code)
            vias.extend([pad_low, pad_high, via])
            via_pairs.append({
                "layers": [low, high],
                "via": via_code,
                "at": [cx, cy],
                "net": net_a,
            })

    report: dict = {
        "engine": "independent power-grid generator (credit: OdaiJ/microwind-power-grid-generator)",
        "spec": {
            "layers": spec.layers,
            "vertical_layers": vertical_layers,
            "horizontal_layers": horizontal_layers,
            "width": spec.width,
            "height": spec.height,
            "columns": spec.columns,
            "rows": spec.rows,
            "wire_width": spec.wire_width,
            "rail_widths": {l: spec.width_for(l) for l in spec.layers},
            "voltage_pattern": pattern,
            "via_size": spec.via_size,
            "via_pad": spec.via_pad,
        },
        "rails_planned": len(planned),
        "rail_rects": [
            {"layer": r.layer, "bbox": [r.x, r.y, r.x2, r.y2], "net": net}
            for r, net in planned
        ],
        "vias_planned": len(via_pairs),
        "collisions": collisions[:50],
        "collision_count": len(collisions),
        "changed": False,
        "preserved_existing": True,
    }

    if spec.check_only:
        return report
    if collisions:
        raise PowerGridError(
            f"{len(collisions)} power-grid rails collide with existing same-layer geometry; "
            "call with check_only=True to inspect, or move/offset the grid"
        )

    # 4. commit -----------------------------------------------------------
    for rect, _net in planned:
        msk.add(rect)
    for via in vias:
        msk.add(via)

    if spec.label_nets:
        _label(msk, planned, spec)

    after = list(msk.rects)
    report["changed"] = True
    report["preserved_existing"] = all(any(a is b for b in after) for a in before)
    report["rectangles_after"] = len(after)
    report["labels"] = {
        spec.vdd_name: sum(1 for l in msk.labels if l.code == POWER_CODES[spec.vdd_name]),
        spec.vss_name: sum(1 for l in msk.labels if l.code == POWER_CODES[spec.vss_name]),
    }
    report["via_pairs"] = via_pairs[:50]
    return report


def _order_by_stack(a: str, b: str) -> tuple[str | None, str | None]:
    from .layers import metal_index

    ia, ib = metal_index(a), metal_index(b)
    if ia is None or ib is None or abs(ia - ib) != 1:
        return None, None
    return (a, b) if ia < ib else (b, a)


def _label(msk: MskFile, planned: list[tuple[Rect, str]], spec: PowerGridSpec) -> None:
    """One label per net, placed on the first rail that carries it."""
    for net, code in ((spec.vdd_name, "$1"), (spec.vss_name, "$0")):
        rail = next((r for r, n in planned if n == net), None)
        if rail is None:
            continue
        msk.add_label(rail.x + rail.w // 2, rail.y + rail.h // 2, net, code, ("1000", "0"))


def generate_power_rails(
    msk: MskFile,
    layer: str,
    count: int,
    pitch: int,
    length: int,
    width: int = 4,
    offset: tuple[int, int] = (0, 0),
    vertical: bool = True,
    net: str = "VDD",
    label: bool = True,
) -> dict:
    """A single-layer stripe bundle — the `generate_power_rails` case."""
    spec = PowerGridSpec(
        layers=[layer],
        width=pitch * count if vertical else length,
        height=length if vertical else pitch * count,
        columns=count if vertical else 1,
        rows=1 if vertical else count,
        column_pitch=pitch if vertical else None,
        row_pitch=pitch if not vertical else None,
        wire_width=width,
        offset=offset,
        voltage_pattern=[net],
        label_nets=label,
    )
    return generate_power_grid(msk, spec)


def analyze_power_grid(msk: MskFile) -> dict:
    """Summarise the power structure already present in a layout."""
    from .checks import connectivity
    from .layers import is_metal

    components = connectivity(msk)
    rails = [
        {"layer": r.layer, "bbox": [r.x, r.y, r.x2, r.y2]}
        for r in msk.rects
        if is_metal(r.layer) and (r.w >= 4 * r.h or r.h >= 4 * r.w)
    ]
    vdd = [l for l in msk.labels if l.code == "$1"]
    vss = [l for l in msk.labels if l.code == "$0"]
    labelled = {
        "VDD": [{"text": l.text, "at": [l.x, l.y]} for l in vdd],
        "VSS": [{"text": l.text, "at": [l.x, l.y]} for l in vss],
    }
    return {
        "rails": rails[:200],
        "rail_count": len(rails),
        "components": len(components),
        "power_labels": labelled,
        "power_components": [
            c for c in components
            if any(l["code"] in ("$1", "$0") for l in c["labels"])
        ][:50],
        "note": "rail detection is a heuristic (aspect ratio >= 4); connectivity uses vias",
    }
