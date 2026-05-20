"""
CSV parser — bytes → ParseResult.

Moved verbatim from ``routers/imports.py:_validate_csv_content`` and renamed
``parse`` so that ``csv_parser`` and ``pdf_parser`` expose the same shape.
Sub-module is deliberately named ``csv_parser`` (not ``csv``) so that the
body can still call ``csv.reader`` from the stdlib without shadowing.
LOCKED (MASON-1).
"""
import csv
import io

from fastapi import HTTPException

from .types import ParseResult


def parse(raw_bytes: bytes, **_ignored) -> ParseResult:
    """Validate-by-result: bytes must decode as UTF-8 *and* parse as CSV with
    at least one data row. Raises 400 with ``kind: parse_error`` on failure.
    Does NOT prove financial structure (BASTION-3 — same gate the legacy fn used).
    """
    try:
        text_content = raw_bytes.decode("utf-8-sig")   # handle BOM
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": "File is not valid UTF-8"},
        )
    try:
        reader = csv.reader(io.StringIO(text_content))
        rows = list(reader)
    except csv.Error as e:
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": str(e)},
        )
    if len(rows) < 2:
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": "File has no data rows"},
        )
    header = rows[0]
    data_rows = rows[1:]
    return ParseResult(header=header, rows=data_rows)
