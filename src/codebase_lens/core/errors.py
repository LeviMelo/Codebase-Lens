from __future__ import annotations


class CblError(Exception):
    """Base class for actionable CBL errors."""


class RootDetectionError(CblError):
    """Raised when CBL cannot detect a valid repository root."""


class PathSafetyError(CblError):
    """Raised when a path escapes the repository root or violates safety policy."""


class OutputWriteError(CblError):
    """Raised when CBL cannot write its output layout."""


class RedactionError(CblError):
    """Raised when safety redaction cannot be performed reliably."""


class TextDecodeError(CblError):
    """Raised when a text file cannot be decoded under the configured policy."""
