"""Programmatic document builders for tests. No committed binaries."""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as rl_canvas


def make_digital_pdf(pages: int = 3, tmp_path: Path | None = None) -> Path:
    """A PDF with a real text layer, one paragraph per page."""
    path = tmp_path / f"digital_{pages}p.pdf" if tmp_path else Path(f"/tmp/digital_{pages}p.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    for i in range(1, pages + 1):
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, f"This is digital page number {i}.")
        c.drawString(72, 700, "It has a proper text layer so it can be extracted directly.")
        c.showPage()
    c.save()
    return path


def make_structured_pdf(tmp_path: Path | None = None) -> Path:
    """A PDF with a title, a section heading, paragraphs and list items."""
    path = tmp_path / "structured.pdf" if tmp_path else Path("/tmp/structured.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, 780, "Quarterly Report")
    c.setFont("Helvetica", 11)
    c.drawString(72, 750, "This is the introduction paragraph.")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, 700, "Findings")
    c.setFont("Helvetica", 11)
    c.drawString(72, 680, "Revenue grew over the quarter.")
    c.drawString(72, 665, "Costs stayed flat across teams.")
    c.drawString(72, 630, "\u2022 First bullet point")
    c.drawString(72, 615, "\u2022 Second bullet point")
    c.drawString(72, 600, "1. Numbered item one")
    c.showPage()
    c.save()
    return path


def make_short_text_pdf(text: str = "Hello world", tmp_path: Path | None = None) -> Path:
    """A PDF whose single page has a real but very short text layer."""
    path = tmp_path / "short.pdf" if tmp_path else Path("/tmp/short.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return path


def make_scanned_pdf(pages: int = 2, tmp_path: Path | None = None) -> Path:
    """A PDF whose pages are raster images with no text layer (needs OCR)."""
    path = tmp_path / f"scanned_{pages}p.pdf" if tmp_path else Path(f"/tmp/scanned_{pages}p.pdf")
    images: list[Image.Image] = []
    for i in range(1, pages + 1):
        img = Image.new("RGB", (595, 842), "white")
        d = ImageDraw.Draw(img)
        d.text((80, 160), f"Scanned invoice number {i}", fill="black")
        d.text((80, 200), "Totally legible scanned content.", fill="black")
        images.append(img)
    images[0].save(str(path), "PDF", resolution=100.0, save_all=True, append_images=images[1:])
    return path


def make_mixed_pdf(text_pages: int = 2, ocr_pages: int = 1, tmp_path: Path | None = None) -> Path:
    """Merge a digital PDF and a scanned PDF so some pages are text, some OCR."""
    from pypdf import PdfWriter

    digital = make_digital_pdf(text_pages, tmp_path)
    scanned = make_scanned_pdf(ocr_pages, tmp_path)
    path = tmp_path / "mixed.pdf" if tmp_path else Path("/tmp/mixed.pdf")
    writer = PdfWriter()
    writer.append(str(digital))
    writer.append(str(scanned))
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def make_docx(
    tmp_path: Path | None = None,
    include_table: bool = True,
    include_image: bool = False,
) -> Path:
    from docx import Document
    from docx.shared import Inches

    path = tmp_path / "sample.docx" if tmp_path else Path("/tmp/sample.docx")
    doc = Document()
    doc.add_heading("Project Status", level=1)
    doc.add_paragraph("This is a lead paragraph about the project.")
    doc.add_paragraph("First bullet point", style="List Bullet")
    doc.add_paragraph("Second bullet point", style="List Bullet")
    if include_table:
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Name"
        table.cell(0, 1).text = "Value"
        table.cell(1, 0).text = "alpha"
        table.cell(1, 1).text = "42"
    doc.add_paragraph("Trailing paragraph after the table.")
    if include_image:
        img_path = tmp_path / "img.png"
        Image.new("RGB", (64, 64), "blue").save(img_path)
        doc.add_picture(str(img_path), width=Inches(0.5))
    doc.save(str(path))
    return path


def make_encrypted_pdf(tmp_path: Path | None = None, password: str = "secret") -> Path:
    """Encrypt a PDF with pypdf; extracting requires the password."""
    from pypdf import PdfReader, PdfWriter

    src = make_digital_pdf(1, tmp_path)
    path = tmp_path / "encrypted.pdf" if tmp_path else Path("/tmp/encrypted.pdf")
    writer = PdfWriter()
    reader = PdfReader(str(src))
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password=password)
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def make_truncated_pdf(tmp_path: Path | None = None) -> Path:
    path = tmp_path / "truncated.pdf" if tmp_path else Path("/tmp/truncated.pdf")
    data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\n%%EOF"  # broken trailer
    path.write_bytes(data)
    return path


def make_garbled_pdf(tmp_path: Path | None = None) -> Path:
    """A PDF with a text layer that is mostly non-alphanumeric (garbled encoding)."""
    path = tmp_path / "garbled.pdf" if tmp_path else Path("/tmp/garbled.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, "\u0001\u0002\u0003\u0004\u0005\u0006" * 10)
    c.showPage()
    c.save()
    return path


def make_plain_zip(tmp_path: Path | None = None) -> Path:
    import zipfile

    path = tmp_path / "plain.zip" if tmp_path else Path("/tmp/plain.zip")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "not a document")
    return path


def make_binary(tmp_path: Path | None = None, ext: str = ".bin") -> Path:
    path = tmp_path / f"random{ext}" if tmp_path else Path(f"/tmp/random{ext}")
    path.write_bytes(os.urandom(128))
    return path