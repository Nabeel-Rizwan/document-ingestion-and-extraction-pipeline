"""Pipeline error hierarchy.

Permanent errors subclass :class:`ExtractionError` and carry a stable machine
``code`` that is persisted onto the Document. Any exception that is *not* an
``ExtractionError`` is treated as transient by the worker and retried up to a
cap.
"""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for permanent, non-retryable extraction failures."""

    code = "internal"

    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code or self.__class__.code
        self.message = message
        super().__init__(message)


class CorruptDocumentError(ExtractionError):
    code = "corrupt"


class EncryptedDocumentError(ExtractionError):
    code = "encrypted"


class UnsupportedFormatError(ExtractionError):
    code = "unsupported"


class EmptyDocumentError(ExtractionError):
    code = "empty"