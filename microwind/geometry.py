"""Rectangle geometry helpers used by the checks and the power-grid engine.

All coordinates are integer lambda units, matching `.MSK`.  Nothing here mutates a
layout; the functions return new values or booleans.
"""

from __future__ import annotations

from dataclasses import dataclass

from .msk import Rect

Box = tuple[int, int, int, int]


def bbox(rects) -> Box | None:
    rects = list(rects)
    if not rects:
        return None
    return (
        min(r.x for r in rects),
        min(r.y for r in rects),
        max(r.x2 for r in rects),
        max(r.y2 for r in rects),
    )


def union_box(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def expand(box: Box, by: int) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def from_box(box: Box, layer: str) -> Rect:
    return Rect.make(box[0], box[1], box[2] - box[0], box[3] - box[1], layer)


def to_box(r: Rect) -> Box:
    return (r.x, r.y, r.x2, r.y2)


def contains(box: Box, x: int, y: int) -> bool:
    """Half-open point test: a point on the upper/right edge is outside."""
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def point_in_rect(r: Rect, x: int, y: int) -> bool:
    return r.x <= x < r.x2 and r.y <= y < r.y2


def overlap_area(a: Rect, b: Rect) -> int:
    dx = min(a.x2, b.x2) - max(a.x, b.x)
    dy = min(a.y2, b.y2) - max(a.y, b.y)
    return dx * dy if dx > 0 and dy > 0 else 0


def gap(a: Rect, b: Rect) -> int:
    """Chebyshev distance between two rectangles (0 when they touch or overlap)."""
    dx = max(a.x - b.x2, b.x - a.x2, 0)
    dy = max(a.y - b.y2, b.y - a.y2, 0)
    return max(dx, dy)


def identical(a: Rect, b: Rect) -> bool:
    return (a.x, a.y, a.w, a.h, a.layer) == (b.x, b.y, b.w, b.h, b.layer)


def merge_boxes(boxes: list[Box]) -> list[Box]:
    """Merge axis-aligned boxes that overlap or touch (same layer)."""
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        out: list[Box] = []
        while boxes:
            cur = boxes.pop()
            i = 0
            while i < len(boxes):
                other = boxes[i]
                if (
                    cur[0] <= other[2] and other[0] <= cur[2]
                    and cur[1] <= other[3] and other[1] <= cur[3]
                ):
                    cur = union_box(cur, other)
                    boxes.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(cur)
        boxes = out
    return sorted(boxes)


@dataclass
class Component:
    """A connected group of same-layer geometry."""

    layer: str
    box: Box
    count: int

    def to_dict(self) -> dict:
        return {"layer": self.layer, "bbox": list(self.box), "rectangles": self.count}


def union_find_components(rects: list[Rect]) -> list[Component]:
    """Group rectangles touching on the same layer into components."""
    groups: dict[str, list[Box]] = {}
    for r in rects:
        groups.setdefault(r.layer, []).append(to_box(r))
    out: list[Component] = []
    for layer, boxes in groups.items():
        merged = merge_boxes(boxes)
        for box in merged:
            n = sum(
                1
                for b in boxes
                if b[0] <= box[2] and box[0] <= b[2] and b[1] <= box[3] and box[1] <= b[3]
            )
            out.append(Component(layer, box, n))
    return out
