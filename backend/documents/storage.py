"""Filesystem access helpers.

The pipeline works on plain filesystem paths. This context manager yields a
real local path for a Document's stored file, copying to a temp file when the
storage backend doesn't expose one (e.g. remote/S3 storage). The pipeline never
changes.
"""

from __future__ import annotations

# os.unlink removes the temporary file during cleanup.
import os
# tempfile creates a local copy when storage exposes no real path.
import tempfile
# contextmanager turns the generator below into a context manager.
from contextlib import contextmanager
# Path object for filesystem operations.
from pathlib import Path
# Iterator type hint for the generator's return value.
from typing import Iterator

# Document whose stored file is being accessed.
from .models import Document


# Decorating the generator makes `with local_path(doc) as p:` work.
@contextmanager
def local_path(document: Document) -> Iterator[Path]:
    # Only attempt the file's .path attribute if a file is actually attached.
    if document.file:
        try:
            # Local storages expose a real filesystem path here.
            path = Path(document.file.path)
        except NotImplementedError:
            # Remote storages (e.g. S3) don't implement .path.
            path = None
        except ValueError:
            # Some backends raise ValueError when no local path is available.
            path = None
        # Use the real path directly when it exists on disk.
        if path is not None and path.exists() and path.is_file():
            yield path
            return

    # Fallback: stream the stored file into a temp file on disk.
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)
        # Copy the storage contents chunk by chunk to bound memory use.
        for chunk in document.file.chunks():
            tmp.write(chunk)
    try:
        # Hand the temporary path to the caller.
        yield tmp_path
    finally:
        # Always delete the temp file, even if the pipeline raised.
        try:
            os.unlink(tmp_path)
        except OSError:
            # Ignore races where the file was already removed.
            pass