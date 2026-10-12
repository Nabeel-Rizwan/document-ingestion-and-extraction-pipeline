"""Programmatic document builders for tests. No committed binaries.

What it does:
    Central factory module that builds minimal, deterministic test documents
    (PDFs, DOCX, ZIPs, raw binaries) on the fly so tests never depend on
    checked-in binary fixtures.

How it works:
    - Uses reportlab to render real PDFs with a text layer (digital),
      Pillow to render image-only PDFs (scanned, needs OCR), pypdf to merge
      or encrypt PDFs, and python-docx to build DOCX files.
    - Every builder accepts an optional pytest ``tmp_path``; when given, the
      file is written inside the isolated test tmp dir, otherwise /tmp is
      used as a fallback for ad-hoc scripts.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as rl_canvas


def make_digital_pdf(pages: int = 3, tmp_path: Path | None = None) -> Path:
    """A PDF with a real text layer, one paragraph per page."""
    # What: builds a multi-page "born-digital" PDF with extractable text.
    # How: draws two text lines per page with reportlab, then showPage()/save().
    path = tmp_path / f"digital_{pages}p.pdf" if tmp_path else Path(f"/tmp/digital_{pages}p.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    for i in range(1, pages + 1):
        c.setFont("Helvetica", 12)
        # Two lines per page: the first line is asserted on in content/search tests.
        c.drawString(72, 720, f"This is digital page number {i}.")
        c.drawString(72, 700, "It has a proper text layer so it can be extracted directly.")
        c.showPage()  # finish current page and start the next one
    c.save()  # flush the PDF to disk
    return path


def make_structured_pdf(tmp_path: Path | None = None) -> Path:
    """A PDF with a title, a section heading, paragraphs and list items."""
    # What: builds a single-page PDF with varied font sizes/styles so the
    #   heading/list classifier has title, h2, paragraphs, bullets, numbers.
    # How: uses bold + larger font sizes as visual heading cues, draws each
    #   logical block at a fixed y-coordinate, then saves one page.
    path = tmp_path / "structured.pdf" if tmp_path else Path("/tmp/structured.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica-Bold", 20)  # large bold -> detected as level-1 heading
    c.drawString(72, 780, "Quarterly Report")
    c.setFont("Helvetica", 11)
    c.drawString(72, 750, "This is the introduction paragraph.")
    c.setFont("Helvetica-Bold", 14)  # smaller bold -> level-2 heading
    c.drawString(72, 700, "Findings")
    c.setFont("Helvetica", 11)
    c.drawString(72, 680, "Revenue grew over the quarter.")
    c.drawString(72, 665, "Costs stayed flat across teams.")
    # Bullet char + numbered prefix are stripped/normalised by the extractor.
    c.drawString(72, 630, "\u2022 First bullet point")
    c.drawString(72, 615, "\u2022 Second bullet point")
    c.drawString(72, 600, "1. Numbered item one")
    c.showPage()
    c.save()
    return path


def make_short_text_pdf(text: str = "Hello world", tmp_path: Path | None = None) -> Path:
    """A PDF whose single page has a real but very short text layer."""
    # What: regression fixture - a terse but real text page that must be
    #   classified as "text", NOT routed to OCR.
    # How: single drawString on one page; caller asserts method == pdf_text.
    path = tmp_path / "short.pdf" if tmp_path else Path("/tmp/short.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return path


def make_scanned_pdf(pages: int = 2, tmp_path: Path | None = None) -> Path:
    """A PDF whose pages are raster images with no text layer (needs OCR)."""
    # What: builds an image-only PDF with zero extractable text.
    # How: renders white Pillow images with black text, then saves them as a
    #   multi-page PDF via save_all/append_images - so no text layer exists.
    path = tmp_path / f"scanned_{pages}p.pdf" if tmp_path else Path(f"/tmp/scanned_{pages}p.pdf")
    images: list[Image.Image] = []
    for i in range(1, pages + 1):
        img = Image.new("RGB", (595, 842), "white")  # roughly A4 at 72dpi
        d = ImageDraw.Draw(img)
        d.text((80, 160), f"Scanned invoice number {i}", fill="black")
        d.text((80, 200), "Totally legible scanned content.", fill="black")
        images.append(img)
    # First image carries save_all + append_images to bundle all pages.
    images[0].save(str(path), "PDF", resolution=100.0, save_all=True, append_images=images[1:])
    return path


def make_mixed_pdf(text_pages: int = 2, ocr_pages: int = 1, tmp_path: Path | None = None) -> Path:
    """Merge a digital PDF and a scanned PDF so some pages are text, some OCR."""
    # What: builds a hybrid PDF to exercise per-page text/OCR routing.
    # How: generates one digital + one scanned PDF above, then concatenates
    #   them with pypdf PdfWriter (digital pages first, scanned last).
    from pypdf import PdfWriter

    digital = make_digital_pdf(text_pages, tmp_path)
    scanned = make_scanned_pdf(ocr_pages, tmp_path)
    path = tmp_path / "mixed.pdf" if tmp_path else Path("/tmp/mixed.pdf")
    writer = PdfWriter()
    writer.append(str(digital))  # first N pages have a text layer
    writer.append(str(scanned))  # trailing pages are image-only -> OCR
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def make_docx(
    tmp_path: Path | None = None,
    include_table: bool = True,
    include_image: bool = False,
) -> Path:
    # What: builds a small DOCX with heading, paragraphs, bullets, table,
    #   and optionally an embedded image (for OCR-of-images tests).
    # How: uses python-docx object model (add_heading/add_paragraph/add_table/
    #   add_picture) then saves to disk.
    from docx import Document
    from docx.shared import Inches

    path = tmp_path / "sample.docx" if tmp_path else Path("/tmp/sample.docx")
    doc = Document()
    doc.add_heading("Project Status", level=1)  # -> heading block, level 1
    doc.add_paragraph("This is a lead paragraph about the project.")
    # "List Bullet" style flags these as list_item blocks in order.
    doc.add_paragraph("First bullet point", style="List Bullet")
    doc.add_paragraph("Second bullet point", style="List Bullet")
    if include_table:
        # 2x2 table with header row + one data row, asserted verbatim.
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Name"
        table.cell(0, 1).text = "Value"
        table.cell(1, 0).text = "alpha"
        table.cell(1, 1).text = "42"
    doc.add_paragraph("Trailing paragraph after the table.")
    if include_image:
        # Tiny blue PNG embedded so the extractor must OCR it, not warn.
        img_path = tmp_path / "img.png"
        Image.new("RGB", (64, 64), "blue").save(img_path)
        doc.add_picture(str(img_path), width=Inches(0.5))
    doc.save(str(path))
    return path


def make_encrypted_pdf(tmp_path: Path | None = None, password: str = "secret") -> Path:
    """Encrypt a PDF with pypdf; extracting requires the password."""
    # What: fixture for the encrypted-document error path.
    # How: copies pages from a fresh digital PDF into a PdfWriter, applies
    #   user-password encryption, then writes out the protected file.
    from pypdf import PdfReader, PdfWriter

    src = make_digital_pdf(1, tmp_path)  # start from valid 1-page PDF
    path = tmp_path / "encrypted.pdf" if tmp_path else Path("/tmp/encrypted.pdf")
    writer = PdfWriter()
    reader = PdfReader(str(src))
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password=password)  # no password supplied at extract time
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def make_truncated_pdf(tmp_path: Path | None = None) -> Path:
    # What: fixture for the corrupt-PDF error path (broken trailer).
    # How: writes raw bytes that start like a PDF but have no valid xref /
    #   page tree, so the parser must raise CorruptDocumentError.
    path = tmp_path / "truncated.pdf" if tmp_path else Path("/tmp/truncated.pdf")
    data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\n%%EOF"  # broken trailer
    path.write_bytes(data)
    return path


def make_garbled_pdf(tmp_path: Path | None = None) -> Path:
    """A PDF with a text layer that is mostly non-alphanumeric (garbled encoding)."""
    # What: fixture for the low-alnum-ratio classifier branch (-> OCR).
    # How: draws control characters only, so extracted text has ~0% alnum
    #   ratio even though a "text layer" technically exists.
    path = tmp_path / "garbled.pdf" if tmp_path else Path("/tmp/garbled.pdf")
    c = rl_canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, "\u0001\u0002\u0003\u0004\u0005\u0006" * 10)
    c.showPage()
    c.save()
    return path


def make_plain_zip(tmp_path: Path | None = None) -> Path:
    # What: a valid ZIP that is NOT a DOCX (DOCX is a ZIP, so this tests
    #   the negative branch of DOCX sniffing).
    # How: creates a zip containing a single hello.txt entry.
    import zipfile

    path = tmp_path / "plain.zip" if tmp_path else Path("/tmp/plain.zip")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "not a document")
    return path


def make_binary(tmp_path: Path | None = None, ext: str = ".bin") -> Path:
    # What: random non-document bytes for unsupported-type tests.
    # How: writes 128 cryptographically random bytes; magic-byte sniffing
    #   must return kind=None for it.
    path = tmp_path / f"random{ext}" if tmp_path else Path(f"/tmp/random{ext}")
    path.write_bytes(os.urandom(128))
    return path
