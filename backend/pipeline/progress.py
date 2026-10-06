"""Progress reporting abstraction.

A pipeline reports progress via a :class:`ProgressReporter`. Fractions are for
the WHOLE pipeline (0..1) and map onto fixed stage bands:

    detecting   0.00 - 0.10
    extracting  0.10 - 0.85
    indexing    0.85 - 1.00   (owned by the Django layer)

The provided implementations are pure Python so the pipeline stays testable
without a database. Django swaps in a DB-backed reporter implementing the same
Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProgressReporter(Protocol):
    def stage(self, name: str, message: str = "") -> None: ...
    def progress(self, fraction: float, message: str = "") -> None: ...


STAGE_BANDS: dict[str, tuple[float, float]] = {
    "detecting": (0.00, 0.10),
    "extracting": (0.10, 0.85),
    "indexing": (0.85, 1.00),
}


def clamp_fraction(fraction: float) -> float:
    return max(0.0, min(1.0, fraction))


def band_progress(stage: str, fraction: float) -> float:
    """Map a 0..1 fraction inside ``stage``'s band to a 0..1 pipeline fraction."""
    low, high = STAGE_BANDS.get(stage, (0.0, 1.0))
    return clamp_fraction(low + (high - low) * clamp_fraction(fraction))


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    progress: float


class NullProgressReporter:
    """Discards all progress calls."""

    def stage(self, name: str, message: str = "") -> None:
        pass

    def progress(self, fraction: float, message: str = "") -> None:
        pass


class RecordingProgressReporter:
    """Stores every event for tests."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def stage(self, name: str, message: str = "") -> None:
        self.events.append(ProgressEvent(stage=name, message=message, progress=0.0))

    def progress(self, fraction: float, message: str = "") -> None:
        self.events.append(ProgressEvent(stage="", message=message, progress=fraction))