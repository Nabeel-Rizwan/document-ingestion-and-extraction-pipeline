"""DB-backed progress reporter.

Implements the pipeline's ``ProgressReporter`` Protocol. It updates the
denormalised Document fields and appends ProgressEvent rows, throttled so we
don't hammer the DB with a row per page:

  * write when the stage changes
  * write when progress advanced >= 0.02
  * write when >= 0.25 s elapsed since the last write
"""

from __future__ import annotations

import time

from django.utils import timezone

from .models import Document, ProgressEvent

MIN_PROGRESS_DELTA = 0.02
MIN_TIME_DELTA = 0.25


class DbProgressReporter:
    def __init__(self, document: Document) -> None:
        self.document = document
        self._last_progress = 0.0
        self._last_write = time.monotonic()
        self._last_stage: str | None = None

    def stage(self, name: str, message: str = "") -> None:
        self._write(stage=name, progress=self._last_progress, message=message)

    def progress(self, fraction: float, message: str = "") -> None:
        fraction = max(0.0, min(1.0, fraction))
        now = time.monotonic()
        advanced = fraction - self._last_progress
        if (
            advanced < MIN_PROGRESS_DELTA
            and now - self._last_write < MIN_TIME_DELTA
            and self._last_stage == self.document.stage
        ):
            return
        self._write(stage=self.document.stage, progress=fraction, message=message)

    def _write(self, *, stage: str, progress: float, message: str) -> None:
        self._last_stage = stage
        self._last_progress = progress
        self._last_write = time.monotonic()

        doc = self.document
        doc.stage = stage
        doc.progress = progress
        doc.save(update_fields=["stage", "progress", "updated_at"])

        ProgressEvent.objects.create(
            document=doc,
            stage=stage,
            message=message,
            progress=progress,
            status=doc.status,
        )