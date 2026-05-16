"""Export-specific exception hierarchy.

Provides typed exceptions for PDF and Excel build failures so that Celery
tasks and the exports router can catch specific errors rather than the
broad ``Exception`` base class.
"""

from __future__ import annotations


class ExportError(Exception):
    """Base class for all export-pipeline errors."""


class PDFBuildError(ExportError):
    """Raised when the WeasyPrint PDF build pipeline fails.

    Callers should catch this to distinguish PDF-specific failures from
    other unexpected errors.
    """


class XlsxBuildError(ExportError):
    """Raised when the openpyxl/XlsxBuilder pipeline fails.

    Callers should catch this to distinguish Excel-specific failures from
    other unexpected errors.
    """
