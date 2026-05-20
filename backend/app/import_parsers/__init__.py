"""
Import parser package — format-specific bytes → ParseResult adapters.

Each sub-module exposes a ``parse(raw_bytes: bytes, ...) -> ParseResult``
function. The router dispatches by file format; the rest of the staged-import
pipeline (preview / patch / commit) is parser-agnostic and operates on the
``header`` + ``rows`` fields of ``ParseResult``.

Sub-modules are named ``csv_parser`` / ``pdf_parser`` (NOT ``csv`` / ``pdf``)
to avoid shadowing the stdlib ``csv`` module that ``csv_parser`` still uses
internally for ``csv.reader``. — LOCKED (MASON-1).
"""
from .types import CandidateTable, ParseResult
from . import csv_parser, pdf_parser

__all__ = ["CandidateTable", "ParseResult", "csv_parser", "pdf_parser", "parse"]


def parse(raw_bytes: bytes, fmt: str, **kwargs):
    """Generic entry point — dispatch by format string.

    Most callers should use the format-specific module directly (cleaner stack
    traces); this helper exists for testing and ad-hoc use.
    """
    fmt = (fmt or "").lower()
    if fmt == "csv":
        return csv_parser.parse(raw_bytes, **kwargs)
    if fmt == "pdf":
        return pdf_parser.parse(raw_bytes, **kwargs)
    raise ValueError(f"Unsupported format: {fmt!r}")
