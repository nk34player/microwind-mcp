"""Minimal PDF report builder (PyMuPDF): headings, wrapped text, tables, images."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image

W, H = 595, 842           # A4 points
M = 42


class Report:
    def __init__(self, path: str | Path, title: str, subtitle: str = ""):
        self.doc = fitz.open()
        self.path = Path(path)
        self.title = title
        self.subtitle = subtitle
        self.page: fitz.Page | None = None
        self.y = M
        self.first_page()

    # ------------------------------------------------------------------ pages
    def first_page(self) -> None:
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=W, height=H)
        self.y = M
        if len(self.doc) == 1:
            self.page.insert_text((M, M + 10), self.title, fontsize=17, fontname="hebo")
            self.y = M + 26
            if self.subtitle:
                self.page.insert_text((M, self.y), self.subtitle, fontsize=10,
                                      fontname="helv", color=(0.35, 0.35, 0.35))
                self.y += 18
            self.page.draw_line((M, self.y), (W - M, self.y), color=(0.6, 0.6, 0.6))
            self.y += 14

    def new_page(self) -> None:
        self._new_page()

    def ensure(self, height: float) -> None:
        """Start a new page unless ``height`` points still fit."""
        if self.y + height > H - M:
            self._new_page()

    def _space(self, need: float) -> None:
        if self.y + need > H - M:
            self._new_page()

    # ----------------------------------------------------------------- blocks
    def heading(self, text: str, size: int = 13) -> None:
        self._space(size + 120)
        self.y += 6
        self.page.insert_text((M, self.y + size), text, fontsize=size, fontname="hebo")
        self.y += size + 8

    def text(self, body: str, size: float = 9.5, gap: float = 6) -> None:
        rect = fitz.Rect(M, self.y, W - M, H - M)
        needed = fitz.get_text_length(body, fontname="helv", fontsize=size)
        approx_lines = max(1, int(needed / (W - 2 * M)) + body.count("\n") + 1)
        self._space(approx_lines * (size + 3) + gap)
        rect = fitz.Rect(M, self.y, W - M, H - M)
        self.page.insert_textbox(rect, body, fontsize=size, fontname="helv",
                                 lineheight=1.35, align=0)
        used = len(body.splitlines() or [""])
        self.y += min(approx_lines, used + (needed // (W - 2 * M))) * (size + 3) + gap

    def bullets(self, items: list[str], size: float = 9.5) -> None:
        for item in items:
            self.text("•  " + item, size=size, gap=2)

    def image(self, path: str | Path, caption: str = "", max_w: float | None = None,
              max_h: float = 300) -> None:
        img = fitz.Pixmap(str(path))
        max_w = max_w or (W - 2 * M)
        scale = min(max_w / img.width, max_h / img.height)
        w, h = img.width * scale, img.height * scale
        self._space(h + (16 if caption else 6))
        # keep the PDF small: raster images are downsampled to ~150 dpi for print
        img_pil = Image.open(path).convert("RGB")
        target_w = max(600, int(w * 2.2))
        if img_pil.width > target_w:
            ratio = target_w / img_pil.width
            img_pil = img_pil.resize((target_w, max(1, int(img_pil.height * ratio))),
                                     Image.LANCZOS)
        buf = io.BytesIO()
        img_pil.save(buf, format="PNG", optimize=True)
        self.page.insert_image(fitz.Rect(M, self.y, M + w, self.y + h),
                               stream=buf.getvalue())
        self.y += h + 4
        if caption:
            import textwrap

            width_chars = max(40, int((W - 2 * M) / 3.9))
            lines = textwrap.wrap(caption, width_chars)
            for i, line in enumerate(lines):
                self.page.insert_text((M, self.y + 9 + i * 10), line, fontsize=8,
                                      fontname="helv", color=(0.35, 0.35, 0.35))
            self.y += 9 + len(lines) * 10

    def table(self, rows: list[list[str]], widths: list[float] | None = None,
              size: float = 8.5, header: bool = True) -> None:
        cols = len(rows[0])
        widths = widths or [(W - 2 * M) / cols] * cols
        line_h = size + 6
        self._space(line_h * len(rows) + 8)
        x0 = M
        for r_i, row in enumerate(rows):
            x = x0
            for c_i, cell in enumerate(row):
                rect = fitz.Rect(x, self.y, x + widths[c_i], self.y + line_h)
                self.page.draw_rect(rect, color=(0.75, 0.75, 0.75), width=0.5)
                if r_i == 0 and header:
                    self.page.draw_rect(rect, color=None, fill=(0.9, 0.92, 0.96))
                self.page.insert_text((x + 3, self.y + line_h - 4), str(cell), fontsize=size,
                                      fontname="hebo" if (r_i == 0 and header) else "helv")
                x += widths[c_i]
            self.y += line_h
        self.y += 8

    def save(self) -> Path:
        """Write atomically; if the target is locked by a viewer, use a suffixed name."""
        import os

        tmp = self.path.with_name(self.path.stem + ".tmp.pdf")
        self.doc.save(tmp, deflate=True, garbage=3)
        self.doc.close()
        try:
            os.replace(tmp, self.path)
            return self.path
        except PermissionError:
            fallback = self.path.with_name(self.path.stem + "_updated.pdf")
            os.replace(tmp, fallback)
            return fallback
