"""Word (.docx) report builder with the same small API as `Report`.

The .docx is the editable master; it is converted to PDF with Word (COM) so the
submitted PDF and the DOCX always match exactly.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.shared import Cm, Inches, Pt, RGBColor


class DocxReport:
    def __init__(self, path: str | Path, title: str, subtitle: str = ""):
        self.path = Path(path)
        self.doc = Document()
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)      # A4
        sec.left_margin = sec.right_margin = Cm(2.0)
        sec.top_margin = sec.bottom_margin = Cm(1.8)
        style = self.doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(10)

        p = self.doc.add_paragraph()
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(18)
        if subtitle:
            q = self.doc.add_paragraph()
            r = q.add_run(subtitle)
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
        self._space = 0

    # ------------------------------------------------------------------ blocks
    def heading(self, text: str, size: int = 13) -> None:
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(size)
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.keep_with_next = True

    def text(self, body: str, size: float = 9.5, gap: float = 6) -> None:
        for line in body.split("\n"):
            p = self.doc.add_paragraph()
            run = p.add_run(line)
            run.font.size = Pt(size)
            p.paragraph_format.space_after = Pt(2)

    def bullets(self, items: list[str], size: float = 9.5) -> None:
        for item in items:
            p = self.doc.add_paragraph(style="List Bullet")
            run = p.add_run(item)
            run.font.size = Pt(size)
            p.paragraph_format.space_after = Pt(2)

    def image(self, path: str | Path, caption: str = "", max_w: float | None = None,
              max_h: float = 300) -> None:
        from PIL import Image

        with Image.open(path) as im:
            w_px, h_px = im.size
        width = Inches(min(6.6, (max_w or 470) / 72))
        # keep the requested max height (points) as the binding constraint
        max_w_in = min(6.6, (max_w or 470) / 72)
        max_h_in = max_h / 72
        scale = min(max_w_in / (w_px / 96), max_h_in / (h_px / 96))
        self.doc.add_picture(str(path), width=Inches(max(1.0, (w_px / 96) * scale)))
        p = self.doc.paragraphs[-1]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if caption:
            c = self.doc.add_paragraph()
            run = c.add_run(caption)
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    def table(self, rows: list[list[str]], widths: list[float] | None = None,
              size: float = 8.5, header: bool = True) -> None:
        cols = len(rows[0])
        table = self.doc.add_table(rows=len(rows), cols=cols)
        table.style = "Table Grid"
        table.autofit = True
        for r_i, row in enumerate(rows):
            for c_i, value in enumerate(row):
                cell = table.cell(r_i, c_i)
                cell.text = ""
                p = cell.paragraphs[0]
                run = p.add_run(str(value))
                run.font.size = Pt(size)
                if r_i == 0 and header:
                    run.bold = True
                if widths:
                    cell.width = Cm(max(1.2, widths[c_i] / 28.0))
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def ensure(self, height: float) -> None:
        """No-op: Word flows pages itself."""

    def new_page(self) -> None:
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def save(self) -> Path:
        self.doc.save(self.path)
        return self.path


def docx_to_pdf(docx_path: str | Path, pdf_path: str | Path | None = None) -> Path:
    """Convert with Word COM; falls back to LibreOffice if Word is unavailable."""
    import os
    import shutil
    import subprocess

    docx_path = Path(docx_path)
    pdf_path = Path(pdf_path) if pdf_path else docx_path.with_suffix(".pdf")
    try:
        import win32com.client as win32

        word = win32.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx_path), ReadOnly=True)
        doc.SaveAs(str(pdf_path), FileFormat=17)       # wdFormatPDF
        doc.Close(False)
        word.Quit()
        return pdf_path
    except Exception:                                  # noqa: BLE001 - fallback path
        pass
    soffice = os.environ.get("LIBREOFFICE_PATH") or shutil.which("soffice")
    if not soffice:
        raise RuntimeError(
            "neither Word nor LibreOffice available for docx->pdf; "
            "install LibreOffice or set LIBREOFFICE_PATH"
        )
    subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                    "--outdir", str(pdf_path.parent), str(docx_path)], check=True)
    return pdf_path
