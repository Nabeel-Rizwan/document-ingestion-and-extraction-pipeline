"""Filesystem access helpers.

The pipeline works on plain filesystem paths. This context manager yields a
real local path for a Document's stored file, copying to a temp file when the
storage backend doesn't expose one (e.g. remote/S3 storage). The pipeline never
changes.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Document


@contextmanager
def local_path(document: Document) -> Iterator[Path]:
    if document.file:
        try:
            path = Path(document.file.path)
        except NotImplementedError:
            path = None
        except ValueError:
            path = None
        if path is not None and path.exists() and path.is_file():
            yield path
            return

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)
        for chunk in document.file.chunks():
            tmp.write(chunk)
    try:
        yield tmp_path
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass