"""Magic-byte sniffing of uploaded files.

File extensions are never trusted. We sniff the first bytes of the file to
decide whether it is really a PDF or a DOCX (a ZIP containing
``word/document.xml``). Anything else gets ``kind=None`` and is rejected later
by the router.
"""

# Enables deferred evaluation of type annotations (PEP 563).
from __future__ import annotations

# `field` supplies the mutable default for `warnings` (a list cannot be a class default).
from dataclasses import dataclass, field
# `Path` provides filesystem path handling for the sniffed file.
from pathlib import Path
# `zipfile` lets us inspect DOCX containers, which are ZIP archives.
import zipfile

# Raised by build_probe when the uploaded file has zero bytes.
from .errors import EmptyDocumentError

# PDF signature bytes that must appear at the start of a real PDF file.
_PDF_MAGIC = b"%PDF-"
# Number of leading bytes read from the file; enough to sample the header.
_SNIFF_BYTES = 1024
# The presence of this member inside the ZIP marks the archive as a DOCX.
_DOCX_MARKER = "word/document.xml"


# Immutable snapshot of the sniffing outcome, passed to routing/selection.
@dataclass(frozen=True)
class FileProbe:
    """The result of sniffing a file's real format."""

    # Path to the file on disk.
    path: Path
    # Original upload filename, used only for the declared extension.
    filename: str
    # Byte size of the file (0 triggers EmptyDocumentError earlier).
    size: int
    # Sniffed format: "pdf", "docx", or None if unrecognised.
    kind: str | None
    # Lowercased extension taken from the filename ("" when none).
    declared_ext: str
    # Non-fatal discrepancies (e.g. extension vs sniffed type) reported upstream.
    warnings: list[str] = field(default_factory=list)


# Lowercase the filename suffix so ".PDF" and ".pdf" compare identically.
def _declared_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    # Return the suffix with its leading dot if present, else an empty string.
    return suffix if suffix.startswith(".") else ""


# Determine whether the archive at ``path`` is really a DOCX by checking its listing.
def _looks_like_docx(path: Path) -> bool:
    try:
        # Open the file as a ZIP archive and list its member names.
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        # Not a valid ZIP at all, so it cannot be a DOCX.
        return False
    # A DOCX must contain the core document part; its absence means not a DOCX.
    return _DOCX_MARKER in names


def build_probe(path: str | Path, filename: str) -> FileProbe:
    """Sniff ``path`` and return a :class:`FileProbe`.

    Raises :class:`EmptyDocumentError` for empty files.
    """
    p = Path(path)
    # Stat the file to learn its size (also confirms the path exists).
    size = p.stat().st_size
    if size == 0:
        # Zero-byte files carry no content, so fail fast with a permanent error.
        raise EmptyDocumentError("The file is empty.")

    # Read only the first _SNIFF_BYTES bytes to sample the magic header.
    with p.open("rb") as fh:
        head = fh.read(_SNIFF_BYTES)

    # Extension from the filename is recorded for warnings/validation only.
    declared = _declared_extension(filename)
    warnings: list[str] = []

    # `kind` stays None until a signature matches (-> rejected by the router).
    kind: str | None = None
    if head.startswith(_PDF_MAGIC):
        # PDF magic bytes matched, so classify the file as a PDF.
        kind = "pdf"
        if declared and declared != ".pdf":
            # Extension disagrees with the sniffed type: keep the sniffed type.
            warnings.append(
                f"File is a PDF but the extension is '{declared or 'none'}'; using sniffed type."
            )
    elif zipfile.is_zipfile(p):
        # Not a PDF but a valid ZIP; check whether it is a DOCX container.
        if _looks_like_docx(p):
            # Archive contains word/document.xml, so it is a DOCX.
            kind = "docx"
            if declared and declared != ".docx":
                # Extension disagrees with the sniffed type: keep the sniffed type.
                warnings.append(
                    f"File is a DOCX but the extension is '{declared or 'none'}'; using sniffed type."
                )
        elif declared == ".docx":
            # Declared as DOCX but the archive is not one; surface a warning.
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