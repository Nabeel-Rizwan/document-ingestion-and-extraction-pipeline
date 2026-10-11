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

# `dataclass` provides the immutable ProgressEvent value object.
from dataclasses import dataclass
# `Protocol` defines the structural contract any reporter must satisfy.
from typing import Protocol


# Structural interface: any object with these two methods is a ProgressReporter.
class ProgressReporter(Protocol):
    # Called when the pipeline moves to a new named stage.
    def stage(self, name: str, message: str = "") -> None: ...
    # Called with a pipeline-wide 0..1 fraction for finer-grained updates.
    def progress(self, fraction: float, message: str = "") -> None: ...


# Fixed pipeline fraction ranges that each named stage occupies.
STAGE_BANDS: dict[str, tuple[float, float]] = {
    "detecting": (0.00, 0.10),
    "extracting": (0.10, 0.85),
    "indexing": (0.85, 1.00),
}


# Clamp any fraction into the valid 0..1 range before it is reported.
def clamp_fraction(fraction: float) -> float:
    return max(0.0, min(1.0, fraction))


# Convert a stage-local fraction into the overall pipeline 0..1 value.
def band_progress(stage: str, fraction: float) -> float:
    """Map a 0..1 fraction inside ``stage``'s band to a 0..1 pipeline fraction."""
    # Unknown stages default to the full 0..1 range so their progress maps 1:1.
    low, high = STAGE_BANDS.get(stage, (0.0, 1.0))
    # Offset the clamped local fraction by the band's low edge, scaled by band width.
    return clamp_fraction(low + (high - low) * clamp_fraction(fraction))


# Immutable record of a single progress/stage notification.
@dataclass(frozen=True)
class ProgressEvent:
    # Stage name ("" for progress-only events).
    stage: str
    # Human-readable description conveyed at the time of the event.
    message: str
    # Pipeline-wide fraction at the time of the event (0.0 for stage events).
    progress: float


# A reporter that accepts and discards every call (useful as a default).
class NullProgressReporter:
    """Discards all progress calls."""

    def stage(self, name: str, message: str = "") -> None:
        # Intentionally does nothing.
        pass

    def progress(self, fraction: float, message: str = "") -> None:
        # Intentionally does nothing.
        pass


# A reporter that appends every event so tests can assert on the sequence.
class RecordingProgressReporter:
    """Stores every event for tests."""

    def __init__(self) -> None:
        # The ordered list of every event received so far.
        self.events: list[ProgressEvent] = []

    def stage(self, name: str, message: str = "") -> None:
        # Record stage transitions with a placeholder progress value.
        self.events.append(ProgressEvent(stage=name, message=message, progress=0.0))

    def progress(self, fraction: float, message: str = "") -> None:
        # Record progress updates with no stage attached.
        self.events.append(ProgressEvent(stage="", message=message, progress=fraction))