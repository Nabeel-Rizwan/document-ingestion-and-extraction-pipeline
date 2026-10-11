"""DB-backed progress reporter.

Implements the pipeline's ``ProgressReporter`` Protocol. It updates the
denormalised Document fields and appends ProgressEvent rows, throttled so we
don't hammer the DB with a row per page:

  * write when the stage changes
  * write when progress advanced >= 0.02
  * write when >= 0.25 s elapsed since the last write
"""

from __future__ import annotations

# Monotonic clock for measuring elapsed time without wall-clock jumps.
import time

# Timezone helpers (imported for timezone-aware datetimes used elsewhere).
from django.utils import timezone

# Document and ProgressEvent models updated by the reporter.
from .models import Document, ProgressEvent

# Minimum progress advance required to force a write.
MIN_PROGRESS_DELTA = 0.02
# Minimum elapsed seconds between writes.
MIN_TIME_DELTA = 0.25


class DbProgressReporter:
    def __init__(self, document: Document) -> None:
        # The document whose denormalised progress fields are updated.
        self.document = document
        # Last persisted progress fraction, used for delta throttling.
        self._last_progress = 0.0
        # Monotonic timestamp of the last write, used for time throttling.
        self._last_write = time.monotonic()
        # Last stage written; a stage change always forces a write.
        self._last_stage: str | None = None

    def stage(self, name: str, message: str = "") -> None:
        # Stage changes always write, reusing the last known progress value.
        self._write(stage=name, progress=self._last_progress, message=message)

    def progress(self, fraction: float, message: str = "") -> None:
        # Clamp the fraction into the valid 0.0-1.0 range.
        fraction = max(0.0, min(1.0, fraction))
        # Current monotonic time for the throttle decision.
        now = time.monotonic()
        # How far progress advanced since the last persisted value.
        advanced = fraction - self._last_progress
        # Skip the write unless progress advanced enough, enough time passed,
        # or the stage changed since the last write.
        if (
            advanced < MIN_PROGRESS_DELTA
            and now - self._last_write < MIN_TIME_DELTA
            and self._last_stage == self.document.stage
        ):
            return
        # Otherwise persist the new progress value.
        self._write(stage=self.document.stage, progress=fraction, message=message)

    def _write(self, *, stage: str, progress: float, message: str) -> None:
        # Remember the write for the next throttle comparison.
        self._last_stage = stage
        self._last_progress = progress
        self._last_write = time.monotonic()

        # Update the denormalised document fields.
        doc = self.document
        doc.stage = stage
        doc.progress = progress
        doc.save(update_fields=["stage", "progress", "updated_at"])

        # Append an event row so SSE clients can observe progress changes.
        ProgressEvent.objects.create(
            document=doc,
            stage=stage,
            message=message,
            progress=progress,
            status=doc.status,
        )