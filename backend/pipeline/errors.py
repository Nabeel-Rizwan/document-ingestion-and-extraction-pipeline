"""Pipeline error hierarchy.

Permanent errors subclass :class:`ExtractionError` and carry a stable machine
``code`` that is persisted onto the Document. Any exception that is *not* an
``ExtractionError`` is treated as transient by the worker and retried up to a
cap.
"""

# Enables deferred evaluation of annotations (PEP 563), so the `str | None`
# union below is not evaluated at class-definition time.
from __future__ import annotations


# Base class for permanent failures: instances are never retried by the worker.
class ExtractionError(Exception):
    """Base class for permanent, non-retryable extraction failures."""

    # Default machine-readable code, overridden by each concrete subclass.
    code = "internal"

    def __init__(self, message: str, code: str | None = None) -> None:
        # Use the per-call code if supplied, otherwise fall back to the class default.
        self.code = code or self.__class__.code
        # Keep the human-readable message as an attribute for persistence/logging.
        self.message = message
        # Also pass the message to Exception so str(err) and tracebacks show it.
        super().__init__(message)


# Raised when the file cannot be parsed at all (damaged container/bytes).
class CorruptDocumentError(ExtractionError):
    # Stable code persisted onto the Document row.
    code = "corrupt"


# Raised when the file is password-protected / encrypted.
class EncryptedDocumentError(ExtractionError):
    # Stable code persisted onto the Document row.
    code = "encrypted"


# Raised when no registered extractor can handle the file's kind.
class UnsupportedFormatError(ExtractionError):
    # Stable code persisted onto the Document row.
    code = "unsupported"


# Raised when the file contains no extractable content.
class EmptyDocumentError(ExtractionError):
    # Stable code persisted onto the Document row.
    code = "empty"