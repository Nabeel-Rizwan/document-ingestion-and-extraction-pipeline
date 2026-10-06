"""Magic-byte sniffing of uploaded files.

File extensions are never trusted. We sniff the first bytes of the file to
decide whether it is really a PDF or a DOCX (a ZIP containing
``word/document.xml``). Anything else gets ``kind=None`` and is rejected later
by the router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import zipfile

from .errors import EmptyDocumentError

_PDF_MAGIC = b"%PDF-"
_SNIFF_BYTES = 1024
_DOCX_MARKER = "word/document.xml"


@dataclass(frozen=True)
class FileProbe:
    """The result of sniffing a file's real format."""

    path: Path
    filename: str
    size: int
    kind: str | None
    declared_ext: str
    warnings: list[str] = field(default_factory=list)


def _declared_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix.startswith(".") else ""


def _looks_like_docx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return False
    return _DOCX_MARKER in names


def build_probe(path: str | Path, filename: str) -> FileProbe:
    """Sniff ``path`` and return a :class:`FileProbe`.

    Raises :class:`EmptyDocumentError` for empty files.
    """
    p = Path(path)
    size = p.stat().st_size
    if size == 0:
        raise EmptyDocumentError("The file is empty.")

    with p.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)

    declared = _declared_extension(filename)
    warnings: list[str] = []

    kind: str | None = None
    if head.startswith(_PDF_MAGIC):
        kind = "pdf"
        if declared and declared != ".pdf":
            warnings.append(
                f"File is a PDF but the extension is '{declared or 'none'}'; using sniffed type."
            )
    elif zipfile.is_zipfile(p):
        if _looks_like_docx(p):
            kind = "docx"
            if declared and declared != ".docx":
                warnings.append(
                    f"File is a DOCX but the extension is '{declared or 'none'}'; using sniffed type."
                )
        elif declared == ".docx":
            warnings.append(
                "File has a .docx extension but is not a DOCX archive; treating as unsupported."
            )

    return FileProbe(
        path=p,
        filename=filename,
        size=size,
        kind=kind,
        declared_ext=declared,
        warnings=warnings,
    )