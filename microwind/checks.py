"""Independent geometric checks.

These are **not** Microwind's native DRC.  They are our own geometric rules derived from
the `.RUL` numbers, and every report says so.  Native verification requires driving the
application; that is out of scope for this build and is labelled as such in the output.

What is implemented:

* minimum width and minimum spacing per layer from `.rul` rule keys
* same-layer overlap detection (identical via pads are excused — Microwind stamps them)
* cross-layer connectivity through vias, with label attachment
* power-net sanity: a `$1`/`$0` label must land on geometry, and VDD must not touch VSS
"""

from __future__ import annotations

from .geometry import gap, merge_boxes, point_in_rect, to_box, union_find_components
from .layers import RULE_KEYS, VIAS, is_via
from .msk import MskFile
from .rul import Technology

ENGINE = "independent-geometry-checks (not Microwind native DRC)"


def _rule(tech: Technology | None, layer: str, which: int) -> int | None:
    if tech is None:
        return None
    keys = RULE_KEYS.get(layer)
    if not keys:
        return None
    value = tech.value(keys[which])
    return int(value) if value else None


def check_width(msk: MskFile, tech: Technology | None = None) -> list[dict]:
    findings: list[dict] = []
    for rect in msk.rects:
        rule = _rule(tech, rect.layer, 0)
        if rule is None:
            continue
        short = min(rect.w, rect.h)
        if short < rule:
            findings.append({
                "rule": "min_width",
                "layer": rect.layer,
                "at": [rect.x, rect.y],
                "size": [rect.w, rect.h],
                "required": rule,
                "message": f"{rect.layer} width {short}λ < {rule}λ at ({rect.x},{rect.y})",
            })
    return findings


def _by_layer(msk: MskFile) -> dict[str, list]:
    """Rectangles grouped by layer, each group sorted by x for a sweep."""
    groups: dict[str, list] = {}
    for rect in msk.rects:
        groups.setdefault(rect.layer, []).append(rect)
    for rects in groups.values():
        rects.sort(key=lambda r: r.x)
    return groups


def check_spacing(msk: MskFile, tech: Technology | None = None) -> list[dict]:
    findings: list[dict] = []
    for layer, rects in _by_layer(msk).items():
        rule = _rule(tech, layer, 1)
        if rule is None:
            continue
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                if b.x - a.x2 >= rule:      # sorted by x: nothing further can be closer
                    break
                d = gap(a, b)
                if 0 < d < rule:
                    findings.append({
                        "rule": "min_spacing",
                        "layer": layer,
                        "between": [[a.x, a.y], [b.x, b.y]],
                        "gap": d,
                        "required": rule,
                        "message": f"{layer} gap {d}λ < {rule}λ between ({a.x},{a.y}) and ({b.x},{b.y})",
                    })
    return findings


def check_overlaps(msk: MskFile) -> list[dict]:
    """Same-layer overlaps that are *not* identical duplicate pads."""
    findings: list[dict] = []
    for layer, rects in _by_layer(msk).items():
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                if b.x >= a.x2:
                    break
                if (a.x, a.y, a.w, a.h) == (b.x, b.y, b.w, b.h):
                    continue
                if a.overlaps(b):
                    findings.append({
                        "rule": "same_layer_overlap",
                        "layer": layer,
                        "area": a.overlaps_area(b),
                        "message": (
                            f"{layer} overlap {a.overlaps_area(b)}λ² "
                            f"at ({a.x},{a.y})/({b.x},{b.y})"
                        ),
                    })
    return findings


CELL = 64          # lambda per spatial bucket; keeps neighbour search O(n·k)
MAX_CELLS_PER_RECT = 8192


def _cell_range(r, cell: int = CELL) -> tuple[range, range]:
    return (
        range(r.x // cell, (r.x2 - 1) // cell + 1),
        range(r.y // cell, (r.y2 - 1) // cell + 1),
    )


def _index(rects: list, cell: int = CELL) -> dict[tuple[str, int, int], list[int]]:
    """Bucket rectangle indices by (layer, cell) so neighbour queries stay local."""
    idx: dict[tuple[str, int, int], list[int]] = {}
    for i, r in enumerate(rects):
        xs, ys = _cell_range(r, cell)
        if (xs.stop - xs.start) * (ys.stop - ys.start) > MAX_CELLS_PER_RECT:
            xs = range(r.x // cell, min(r.x // cell + 1, xs.stop))
            ys = range(r.y // cell, min(r.y // cell + 1, ys.stop))
        for cx in xs:
            for cy in ys:
                idx.setdefault((r.layer, cx, cy), []).append(i)
    return idx


def _candidates(idx: dict, layer: str, r, cell: int = CELL) -> set[int]:
    out: set[int] = set()
    xs, ys = _cell_range(r, cell)
    for cx in range(xs.start - 1, xs.stop + 1):
        for cy in range(ys.start - 1, ys.stop + 1):
            out.update(idx.get((layer, cx, cy), ()))
    return out


METAL_TO_VIA = {metal: via for via, pair in VIAS.items() for metal in pair}


def _node_edges(msk: MskFile) -> list[tuple[int, int]]:
    """Index pairs that are electrically connected (same layer or through a via)."""
    rects = msk.rects
    idx = _index(rects)
    edges: set[tuple[int, int]] = set()

    def link(i: int, j: int) -> None:
        if i != j:
            edges.add((i, j) if i < j else (j, i))

    # same-layer touching geometry
    for i, a in enumerate(rects):
        for j in _candidates(idx, a.layer, a):
            if j != i and a.touches(rects[j]):
                link(i, j)

    # metal <-> via
    for i, a in enumerate(rects):
        if is_via(a.layer):
            for metal in VIAS[a.layer]:
                for j in _candidates(idx, metal, a):
                    if a.touches(rects[j]):
                        link(i, j)
        elif a.layer in METAL_TO_VIA:
            via_layer = METAL_TO_VIA[a.layer]
            for j in _candidates(idx, via_layer, a):
                if a.touches(rects[j]):
                    link(i, j)
    return sorted(edges)


def connectivity(msk: MskFile) -> list[dict]:
    """Connected components of geometry, plus the labels that land on them."""
    rects = msk.rects
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in _node_edges(msk):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    groups: dict[int, list[int]] = {}
    for i in range(len(rects)):
        groups.setdefault(find(i), []).append(i)

    components = []
    for members in sorted(groups.values(), key=lambda m: -len(m)):
        boxes = [to_box(rects[i]) for i in members]
        merged = merge_boxes(boxes)
        box = (
            min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes),
        )
        labels = []
        for label in msk.labels:
            if any(point_in_rect(rects[i], label.x, label.y) for i in members):
                labels.append({"text": label.text, "code": label.code})
        components.append({
            "bbox": list(box),
            "rectangles": len(members),
            "merged_shapes": len(merged),
            "layers": sorted({rects[i].layer for i in members}),
            "labels": labels,
        })
    return components


def check_power(msk: MskFile) -> dict:
    """Do the VDD/VSS labels land on geometry, and do the two nets stay apart?"""
    labels = msk.labels
    vdd = [l for l in labels if l.code == "$1"]
    vss = [l for l in labels if l.code == "$0"]
    rects = msk.rects

    dangling = [
        {"text": l.text, "code": l.code, "at": [l.x, l.y]}
        for l in vdd + vss
        if not any(point_in_rect(r, l.x, l.y) for r in rects)
    ]

    components = connectivity(msk)
    shorted = [
        c for c in components
        if any(l["code"] == "$1" for l in c["labels"]) and any(l["code"] == "$0" for l in c["labels"])
    ]
    return {
        "label_count": {"VDD": len(vdd), "VSS": len(vss)},
        "unattached_labels": dangling,
        "shorted_components": [
            {"bbox": c["bbox"], "rectangles": c["rectangles"],
             "labels": [l["text"] for l in c["labels"]]}
            for c in shorted
        ],
        "ok": not dangling and not shorted,
    }


def run_all(msk: MskFile, tech: Technology | None = None, limits: tuple[int, int] = (50, 50)) -> dict:
    """Full independent report. Findings are truncated to keep reports readable."""
    width = check_width(msk, tech)
    spacing = check_spacing(msk, tech)
    overlaps = check_overlaps(msk)
    components = connectivity(msk)
    power = check_power(msk)
    total_width_checks = sum(1 for r in msk.rects if _rule(tech, r.layer, 0) is not None)
    total_spacing_layers = sorted({r.layer for r in msk.rects if _rule(tech, r.layer, 1) is not None})
    return {
        "engine": ENGINE,
        "native_drc_run": False,
        "technology": tech.summary() if tech else None,
        "summary": {
            "rectangles": len(msk.rects),
            "labels": len(msk.labels),
            "components": len(components),
            "min_width_violations": len(width),
            "min_spacing_violations": len(spacing),
            "same_layer_overlaps": len(overlaps),
            "width_checked_rectangles": total_width_checks,
            "spacing_checked_layers": total_spacing_layers,
            "skipped_layers": sorted(
                {r.layer for r in msk.rects} - set(RULE_KEYS)
            ),
        },
        "power": power,
        "violations": {
            "min_width": width[:limits[0]],
            "min_spacing": spacing[:limits[1]],
            "truncated": len(width) > limits[0] or len(spacing) > limits[1],
        },
    }
