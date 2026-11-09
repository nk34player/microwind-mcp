"""Drawings produced from real geometry / netlists (no app screenshots).

Everything here is a *rendering of our own data*: layout rectangles from the
`.MSK` model, cross-sections taken through actual rectangle coordinates, stick
diagrams from the same nets.  The images are labelled as such in the report -
they are not captures of a Microwind window.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .logic import Circuit, Transistor
from .msk import MskFile

#: layer -> fill colour (Microwind-like, readable in print)
LAYER_COLORS = {
    "NW": (255, 236, 179),
    "DN": (124, 200, 96),
    "DP": (196, 150, 76),
    "PO": (214, 69, 65),
    "CO": (40, 40, 40),
    "ME": (58, 110, 200),
    "M2": (176, 66, 176),
    "M3": (0, 160, 170),
    "M4": (120, 120, 120),
    "VI": (0, 0, 0),
    "V2": (0, 0, 0),
}
#: draw order, bottom first
LAYER_ORDER = ["NW", "DN", "DP", "PO", "CO", "ME", "M2", "M3", "M4", "VI", "V2"]

#: z position for a cross-section (higher = further from the substrate)
LAYER_Z = {
    "NW": 0.5, "DN": 1, "DP": 1, "PO": 2, "CO": 3, "ME": 4, "VI": 3.5,
    "M2": 5, "V2": 4.5, "M3": 6,
}


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def layout_png(msk: MskFile, path: str | Path, scale: int = 6,
               max_y: int | None = None,
               x_range: tuple[int, int] | None = None) -> Path:
    box = msk.bbox or (0, 0, 100, 100)
    x0, y0, x1, y1 = box
    if max_y is not None:
        y1 = min(y1, max_y)
    if x_range is not None:
        x0, x1 = x_range
    pad = 8
    w = (x1 - x0 + 2 * pad) * scale
    h = (y1 - y0 + 2 * pad) * scale
    img = Image.new("RGB", (max(w, 10), max(h, 10)), "white")
    d = ImageDraw.Draw(img)
    rects = [r for r in msk.rects
             if (max_y is None or r.y < y1)
             and (x_range is None or (r.x < x1 and r.x2 > x0))]
    for layer in LAYER_ORDER:
        for r in rects:
            if r.layer != layer:
                continue
            px = (r.x - x0 + pad) * scale
            py = (y1 - r.y2 + pad) * scale
            color = LAYER_COLORS.get(layer, (200, 200, 200))
            if layer in ("M2", "M3"):
                # stubs are drawn hollow so the devices underneath stay visible
                d.rectangle([px, py, px + r.w * scale, py + r.h * scale],
                            fill=None, outline=color, width=1)
            else:
                d.rectangle([px, py, px + r.w * scale, py + r.h * scale],
                            fill=color, outline=(80, 80, 80))
    out = Path(path)
    img.save(out)
    return out


def layout_legend(path: str | Path, msk: MskFile, scale: int = 1) -> Path:
    """Small legend image listing the layers that actually occur."""
    used = [l for l in LAYER_ORDER if any(r.layer == l for r in msk.rects)]
    img = Image.new("RGB", (260, 26 * (len(used) + 1)), "white")
    d = ImageDraw.Draw(img)
    f = _font(16)
    d.text((6, 4), "Layers", fill="black", font=f)
    for i, layer in enumerate(used):
        y = 26 + i * 24
        d.rectangle([6, y, 30, y + 16], fill=LAYER_COLORS[layer], outline="black")
        d.text((38, y - 1), layer, fill="black", font=f)
    out = Path(path)
    img.save(out)
    return out


def cross_section_png(msk: MskFile, axis: str, at: int, path: str | Path,
                      span: tuple[int, int] | None = None,
                      scale: int = 10) -> Path:
    """Cut through ``y = at`` (axis="y", an N/P strip) or ``x = at`` (axis="x").

    For each x (or y) along the cut the layers crossing it are stacked by
    :data:`LAYER_Z`, so contacts and the metal stack appear where they really
    are.  The result is a drawing of the layout geometry, not a screenshot.
    """
    rects = msk.rects
    if axis == "y":
        lo, hi = span or ((min(r.x for r in rects), max(r.x2 for r in rects)))
        hits = [r for r in rects if r.y <= at < r.y2]
        coord = lambda r, v: r.x <= v < r.x2  # noqa: E731
    else:
        lo, hi = span or ((min(r.y for r in rects), max(r.y2 for r in rects)))
        hits = [r for r in rects if r.x <= at < r.x2]
        coord = lambda r, v: r.y <= v < r.y2  # noqa: E731

    zmax = 6
    w = (hi - lo) * scale + 40
    h = (zmax + 2) * 34 + 20
    img = Image.new("RGB", (max(w, 100), h), "white")
    d = ImageDraw.Draw(img)
    base_y = h - 30
    d.line([20, base_y, w - 10, base_y], fill="black", width=2)
    f = _font(13)

    for layer, z in LAYER_Z.items():
        segs: list[tuple[int, int]] = []
        for r in hits:
            if r.layer != layer:
                continue
            a, b = (r.x, r.x2) if axis == "y" else (r.y, r.y2)
            a, b = max(a, lo), min(b, hi)
            if b > a:
                segs.append((a, b))
        segs.sort()
        merged: list[tuple[int, int]] = []
        for a, b in segs:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        for a, b in merged:
            y0 = base_y - z * 28
            d.rectangle([20 + (a - lo) * scale, y0, 20 + (b - lo) * scale, y0 + 18],
                        fill=LAYER_COLORS.get(layer, (200, 200, 200)), outline="black")
            d.text((24 + (a - lo) * scale, y0 + 1), layer, fill="black", font=f)

    d.text((20, 4), f"cross-section {axis}={at} (lambda units, {lo}..{hi})", fill="black", font=f)
    d.text((20, base_y + 6), "substrate", fill="black", font=f)
    out = Path(path)
    img.save(out)
    return out


def _transistor_symbol(d: ImageDraw.ImageDraw, x: int, y: int, kind: str,
                       gate: str, width: int, label: str, vertical: bool = True) -> None:
    """Very small MOSFET symbol: channel bar, gate plate, arrows optional."""
    color = (30, 30, 30)
    if vertical:
        d.line([x, y, x, y + 34], fill=color, width=3)
        d.line([x + 8, y + 6, x + 8, y + 28], fill=color, width=2)
        d.line([x + 8, y + 17, x + 22, y + 17], fill=color, width=2)
        d.text((x + 24, y + 8), f"{gate}", fill="black", font=_font(12))
        arrow = (x + 4, y + 30) if kind == "n" else (x + 4, y + 4)
        d.polygon([arrow, (arrow[0] + 6, arrow[1] - 4), (arrow[0] + 6, arrow[1] + 4)], fill=color)
    else:
        d.line([x, y, x + 34, y], fill=color, width=3)
        d.line([x + 6, y + 8, x + 28, y + 8], fill=color, width=2)
        d.line([x + 17, y + 8, x + 17, y + 22], fill=color, width=2)
        d.text((x + 2, y + 24), f"{gate}", fill="black", font=_font(12))
    d.text((x + 20, y - 16), f"{width}/2", fill=(60, 60, 140), font=_font(10))


def _fet(d: ImageDraw.ImageDraw, x: int, y_top: int, y_bot: int, name: str,
         kind: str, f) -> None:
    """Vertical FET on a wire from y_top to y_bot, gate lead to the right."""
    mid = (y_top + y_bot) // 2
    sym = 12
    col = (30, 30, 30)
    d.line([x, y_top, x, mid - sym], fill=col, width=2)
    d.line([x, mid + sym, x, y_bot], fill=col, width=2)
    d.line([x, mid - sym, x, mid + sym], fill=col, width=3)            # channel
    d.line([x + 7, mid - sym + 2, x + 7, mid + sym - 2], fill=(110, 110, 110), width=2)
    d.line([x + 7, mid, x + 24, mid], fill=col, width=2)               # gate
    d.text((x + 26, mid - 6), name, fill=(20, 20, 110), font=f)
    d.text((x + 26, mid + 6), "pMOS" if kind == "p" else "nMOS",
           fill=(150, 150, 150), font=_font(8))


def _draw_tree(d: ImageDraw.ImageDraw, tree, x0: int, x1: int, y_top: int, y_bot: int,
               kind: str, f) -> None:
    op = tree[0]
    if op == "var":
        _fet(d, (x0 + x1) // 2, y_top, y_bot, tree[1], kind, f)
        return
    if op == "series":
        n = len(tree[1])
        h = (y_bot - y_top) / n
        for i, child in enumerate(tree[1]):
            _draw_tree(d, child, x0, x1, int(y_top + i * h), int(y_top + (i + 1) * h), kind, f)
        return
    n = len(tree[1])
    w = (x1 - x0) / n
    for i, child in enumerate(tree[1]):
        _draw_tree(d, child, int(x0 + i * w), int(x0 + (i + 1) * w), y_top, y_bot, kind, f)


def schematic_png(circuit: Circuit, path: str | Path) -> Path:
    """Transistor-level schematic drawn from the synthesized series/parallel trees."""
    stages = circuit.stages
    width = max(820, 250 * len(stages) + 80)
    height = 640
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f = _font(11)
    fs = _font(10)
    ft = _font(12)
    d.text((16, 8), f"{circuit.name} = {circuit.expression}", fill="black", font=ft)
    d.text((16, 26), "transistor schematic (W/L in the table; unit inverter 4/2 nMOS, 8/2 pMOS)",
           fill=(110, 110, 110), font=fs)

    y_vdd, y_out, y_vss = 80, 300, 560
    col_w = (width - 60) // max(1, len(stages))
    for ci, stage in enumerate(stages):
        x0 = 30 + ci * col_w
        x1 = x0 + col_w
        d.rectangle([x0 + 6, 56, x1 - 20, height - 40], outline=(215, 215, 215))
        d.text((x0 + 14, 60), f"{stage['stage']}  ({stage.get('gate', 'COMPLEX')})",
               fill="black", font=fs)
        d.line([x0 + 14, y_vdd, x1 - 24, y_vdd], fill=(20, 20, 20), width=2)
        d.text((x0 + 14, y_vdd - 12), "VDD", fill="black", font=fs)
        d.line([x0 + 14, y_vss, x1 - 24, y_vss], fill=(20, 20, 20), width=2)
        d.text((x0 + 14, y_vss + 2), "VSS", fill="black", font=fs)

        pad = 40
        _draw_tree(d, stage["pun_tree"], x0 + pad + 30, x1 - pad, y_vdd, y_out, "p", f)
        _draw_tree(d, stage["pdn_tree"], x0 + pad + 30, x1 - pad, y_out, y_vss, "n", f)
        d.line([x0 + pad, y_out, x1 - pad, y_out], fill=(20, 20, 20), width=2)
        d.text((x0 + 14, y_out - 6), stage["output"], fill=(150, 20, 20), font=f)

    d.text((16, height - 22), "generated from the same netlist that drives the layout and the SPICE deck",
           fill=(150, 150, 150), font=fs)
    out = Path(path)
    img.save(out)
    return out


def stick_png(msk: MskFile, path: str | Path, scale: int = 8,
              max_y: int = 40) -> Path:
    """Stick view of the cell: diffusion, poly, metal sticks + contact dots.

    Routing metal2/metal3 stubs are left out, so the drawing reads like a stick
    diagram instead of a full layout.
    """
    box = msk.bbox or (0, 0, 100, 100)
    x0, y0, x1, _y1 = box
    rects = [r for r in msk.rects if r.y < max_y]
    pad = 6
    img = Image.new("RGB", ((x1 - x0 + 2 * pad) * scale, (max_y + 2 * pad) * scale), "white")
    d = ImageDraw.Draw(img)
    f = _font(10)
    colors = {"DN": (0, 150, 0), "DP": (170, 120, 20), "PO": (210, 30, 30),
              "ME": (30, 90, 210), "NW": (235, 215, 150)}
    order = ["NW", "DP", "DN", "PO", "ME"]
    for layer in order:
        for r in rects:
            if r.layer != layer:
                continue
            a = (r.x - x0 + pad) * scale
            b = (max_y - r.y2 + pad) * scale
            c = a + r.w * scale
            e = b + r.h * scale
            if layer == "NW":
                d.rectangle([a, b, c, e], outline=colors[layer])
            elif layer == "ME":
                d.rectangle([a, b, c, e], fill=colors[layer])
            else:
                d.rectangle([a, b, c, e], outline=colors[layer], width=3)
            if layer in ("DN", "DP"):
                d.text((a + 2, b - 11), layer, fill=colors[layer], font=f)
    for r in rects:
        if r.layer in ("CO", "VI"):
            cx = (r.x + r.w / 2 - x0 + pad) * scale
            cy = (max_y - (r.y + r.h / 2) + pad) * scale
            d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill="black")
    out = Path(path)
    img.save(out)
    return out


def plot_waves(waves: str | Path, inputs: list[str], out: str, path: str | Path,
               delays: dict | None = None) -> Path:
    """Clock / output waveform plot (matplotlib, no app window involved)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times, data = [], {}
    with Path(waves).open() as fh:
        header = fh.readline().split()
        cols = {h: i for i, h in enumerate(header)}
        for line in fh:
            parts = line.split()
            if len(parts) < len(header):
                continue
            times.append(float(parts[cols["time"]]) * 1e9)
            for name in inputs + [out]:
                key = f"v({name})"
                if key in cols:
                    data.setdefault(name, []).append(float(parts[cols[key]]))

    fig, ax = plt.subplots(figsize=(11, 6))
    offset = 0.0
    for name in inputs + [out]:
        if name not in data:
            continue
        ax.plot(times, [v + offset for v in data[name]], lw=1.6,
                label=name, color=("#d62728" if name == out else "#1f77b4"))
        ax.text(-0.4, offset + 0.5, name, ha="right", va="center", fontsize=10)
        offset += 1.5
    ax.set_xlabel("time (ns)")
    ax.set_yticks([])
    ax.set_xlim(0, max(times))
    ax.grid(axis="x", alpha=0.3)
    ax.set_title(f"Transient simulation (ngspice): {out} vs {', '.join(inputs)}", fontsize=10)
    if delays:
        txt = "  ".join(
            f"t{name} LH={v.get('tpLH_ps','-')} HL={v.get('tpHL_ps','-')} ps"
            for name, v in delays.items())
        ax.text(0.01, 0.01, txt, transform=ax.transAxes, fontsize=8, color="#555")
    fig.tight_layout()
    out_path = Path(path)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
