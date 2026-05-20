"""
PDF parser — bytes → ParseResult.

Ports the v1.3.2 ``_extract_pdf_dataframe`` (commit ``4451b97``) into a
self-contained module that:

* runs pdfplumber in a child process with a 30s wall-clock kill
  (BASTION Q1 worker-process boundary);
* enforces page / row / table caps (BASTION-2);
* generalises the institution-shaped two-date text fallback to a 3-pattern
  regex set tried in order (MASON Q7);
* surfaces every multi-row candidate table to the caller so the wizard can
  let the user pick when N > 1;
* returns generic client errors and logs only the exception class name in
  normal mode (BASTION-3 sanitisation);
* drops the pandas dependency — emits list[list[str]] directly.

LOCKED in Option B spec § 3 + § 4.2 + § 7.2 + § 7.3 + § 7.5.
"""
from __future__ import annotations

import io
import logging
import multiprocessing
import os
import re
from collections import Counter
from typing import List, Optional

from fastapi import HTTPException

from .types import CandidateTable, ParseResult


log = logging.getLogger(__name__)

# ─── Caps (BASTION-2) ────────────────────────────────────────────────────────
MAX_PDF_PAGES = 200
MAX_PDF_ROWS = 50_000
MAX_TABLES_PER_PAGE = 50
WORKER_TIMEOUT_SECONDS = 30

# Visible preview limits (§ 7.4)
PREVIEW_MAX_CELLS = 5
PREVIEW_CELL_CHAR_CAP = 80

# Generic error message — never leaks underlying exception detail to clients (§ 7.5).
_GENERIC_PARSE_ERROR = "PDF could not be opened"


# ─── Three-pattern text-fallback regex set (MASON Q7) ────────────────────────
# Tried in order; first pattern whose row count meets the "more rows than table
# extraction" gate is used. Adding a fourth pattern is a one-line append.
_TX_PATTERNS = [
    # (a) Cr/Dr suffix — e.g. "$1,234.56 Cr"
    re.compile(
        r"(\d{2}/\d{2}/\d{2,4})\s+"
        r"(\d{2}/\d{2}/\d{2,4})\s+"
        r"(.+?)\s+"
        r"(\$[\d,]+\.\d{2}\s*(?:Cr|Dr))"
    ),
    # (b) Signed decimal — e.g. "-1234.56" or "1234.56"
    re.compile(
        r"(\d{2}/\d{2}/\d{2,4})\s+"
        r"(\d{2}/\d{2}/\d{2,4})\s+"
        r"(.+?)\s+"
        r"(-?\$?[\d,]+\.\d{2})"
    ),
    # (c) Parens-negative — e.g. "(1234.56)"
    re.compile(
        r"(\d{2}/\d{2}/\d{2,4})\s+"
        r"(\d{2}/\d{2}/\d{2,4})\s+"
        r"(.+?)\s+"
        r"(\(\$?[\d,]+\.\d{2}\))"
    ),
]


# ─── Worker entry point ──────────────────────────────────────────────────────

def _extract_in_worker(raw_bytes: bytes, queue: "multiprocessing.Queue") -> None:
    """Run pdfplumber in a child process. Puts a ``(kind, payload)`` tuple on
    the queue:

      * ``("ok", (header, rows, candidates, strategy))`` on success
      * ``("error", (status_code, message))`` on a recoverable parse error
        (oversize, no-tables, etc.) — these are user-facing
      * ``("exception", exc_class_name)`` on an unexpected error — surfaces as
        a generic client message; the class name is logged server-side only.
    """
    try:
        import pdfplumber  # imported inside the worker for fork-safety

        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            page_count = len(pdf.pages)
            if page_count > MAX_PDF_PAGES:
                queue.put((
                    "error",
                    (413, f"PDF exceeds {MAX_PDF_PAGES}-page limit (got {page_count})"),
                ))
                return

            tables: List[List[List[Optional[str]]]] = []
            for page in pdf.pages:
                page_tables = page.extract_tables() or []
                if len(page_tables) > MAX_TABLES_PER_PAGE:
                    queue.put((
                        "error",
                        (400, f"PDF page exceeds {MAX_TABLES_PER_PAGE}-tables-per-page limit"),
                    ))
                    return
                for table in page_tables:
                    if table:
                        tables.append(table)

            # Text fallback needs the raw text per page; gather here while the
            # PDF is still open so we don't reopen later.
            page_texts = [(page.extract_text() or "") for page in pdf.pages]

        if not tables:
            queue.put(("error", (422, "No tables found in PDF")))
            return

        single_row = [t for t in tables if len(t) == 1]
        multi_row = [t for t in tables if len(t) > 1]

        # ── Row-per-table layout ────────────────────────────────────────────
        # Single-row tables outnumber multi-row by >2× *and* there are at
        # least 4 of them (matches the v1.3.2 heuristic).
        if len(single_row) > max(len(multi_row) * 2, 3):
            header, rows, strategy = _flatten_row_per_table(single_row, page_texts)
            candidates = [
                CandidateTable(
                    index=0,
                    row_count=len(rows),
                    column_count=len(header),
                    header=header,
                    rows=rows,
                    first_row_preview=_clip_preview(rows[0] if rows else []),
                )
            ]
        else:
            # Standard layout: merge multi-row tables that share an identical
            # normalised header (v1.3.2 behaviour — a transactions table that
            # spans pages comes back from pdfplumber as N tables with the
            # same header; we re-stitch them so the wizard sees one
            # candidate, not N. Different-header tables stay separate.)
            merged_multi_row = _merge_same_header_tables(multi_row)
            candidates = _build_candidates(merged_multi_row, fallback_when_empty=tables)
            strategy = "standard"
            # Default selection = largest candidate by row_count.
            if candidates:
                largest = max(candidates, key=lambda c: c.row_count)
                header = largest.header
                rows = largest.rows
            else:
                header, rows = [], []

        if len(rows) > MAX_PDF_ROWS:
            queue.put((
                "error",
                (400, f"PDF produced {len(rows)} rows; limit is {MAX_PDF_ROWS}"),
            ))
            return

        queue.put(("ok", (header, rows, candidates, strategy)))

    except Exception as exc:  # pragma: no cover — defensive
        queue.put(("exception", type(exc).__name__))


def _normalise_header(row: List[Optional[str]]) -> tuple:
    """Cell-by-cell normalisation for header equality — strip + casefold.
    Handles whitespace and case drift across continuation pages (e.g. "Date "
    on page 1 vs "DATE" on page 2 still merges).
    """
    return tuple((str(c) if c is not None else "").strip().casefold() for c in row)


def _merge_same_header_tables(
    multi_row_tables: List[List[List[Optional[str]]]],
) -> List[List[List[Optional[str]]]]:
    """Group multi-row tables by their normalised header (cell-by-cell, same
    column count) and merge each N>1 group into one table — header from the
    first member, data rows concatenated in page order.

    Defensive: drops any data row that exactly matches the normalised header
    (handles pdfplumber occasionally mis-classifying a continuation page's
    header as a data row).

    v1.3.2 parity: a transactions table that spans pages re-stitches into a
    single candidate. Different-header tables (e.g. summary + transactions)
    stay separate.
    """
    # Order-preserving grouping: groups[key] = (header_norm, [tables_in_order])
    groups: List[tuple] = []  # list of (key, [tables])
    for table in multi_row_tables:
        if not table:
            continue
        header_norm = _normalise_header(table[0])
        key = (len(table[0]), header_norm)
        # Linear scan is fine here — N is at most MAX_TABLES_PER_PAGE *
        # MAX_PDF_PAGES, and the inner loop is just a tuple eq.
        for existing_key, members in groups:
            if existing_key == key:
                members.append(table)
                break
        else:
            groups.append((key, [table]))

    merged: List[List[List[Optional[str]]]] = []
    for (_col_count, header_norm), members in groups:
        if len(members) == 1:
            merged.append(members[0])
            continue
        # Header from the first member (already proven cell-equal under
        # normalisation; preserves any original casing/whitespace the caller
        # might want to display).
        first = members[0]
        combined: List[List[Optional[str]]] = [first[0]]
        for tbl in members:
            for row in tbl[1:]:
                # Drop defensive: continuation-page header mis-classified
                # as data by pdfplumber. Normalise both sides for the check.
                if _normalise_header(row) == header_norm and len(row) == len(first[0]):
                    continue
                combined.append(row)
        merged.append(combined)
    return merged


def _build_candidates(
    multi_row_tables: List[List[List[Optional[str]]]],
    fallback_when_empty: List[List[List[Optional[str]]]],
) -> List[CandidateTable]:
    """Turn every multi-row table into a CandidateTable. Falls back to the full
    table list if there are no multi-row tables (e.g. one-row "summary" PDFs).
    """
    src = multi_row_tables if multi_row_tables else fallback_when_empty
    out: List[CandidateTable] = []
    for idx, table in enumerate(src):
        header_raw = table[0]
        header = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(header_raw)]
        rows = [
            [str(c).strip() if c is not None else "" for c in row]
            for row in table[1:]
        ]
        first_row = rows[0] if rows else header
        out.append(CandidateTable(
            index=idx,
            row_count=len(rows),
            column_count=len(header),
            header=header,
            rows=rows,
            first_row_preview=_clip_preview(first_row),
        ))
    return out


def _flatten_row_per_table(single_row_tables, page_texts):
    """Row-per-table layout: every transaction is its own 1-row table.
    Find the dominant column count, identify the most-frequent row as the
    repeating header, flatten the rest. Optionally fall through to text
    fallback when the header has two date columns and pdfplumber under-counts.
    """
    col_counts = Counter(len(t[0]) for t in single_row_tables if t)
    if not col_counts:
        # Should be unreachable — caller checks tables is non-empty.
        return [], [], "row_per_table"
    target_cols = col_counts.most_common(1)[0][0]
    candidates = [t for t in single_row_tables if t and len(t[0]) == target_cols]

    row_counter = Counter(
        tuple(str(c).strip() if c else "" for c in t[0]) for t in candidates
    )
    header_tuple = row_counter.most_common(1)[0][0]
    headers = list(header_tuple)

    rows: List[List[str]] = []
    for t in candidates:
        row = [str(c).strip() if c is not None else "" for c in t[0]]
        if tuple(row) != header_tuple:
            rows.append(row)

    date_col_indices = [i for i, h in enumerate(headers) if "date" in h.lower()]
    if len(date_col_indices) == 2:
        text_rows = _extract_with_pattern_set(page_texts)
        if len(text_rows) > len(rows):
            # Text fallback found more rows than table extraction. Strip the
            # processed-date column from the header — text fallback only
            # surfaces the transaction date.
            kept_date_header = headers[date_col_indices[1]]
            non_date_headers = [
                h for i, h in enumerate(headers) if i not in date_col_indices
            ]
            headers = [kept_date_header] + non_date_headers
            return headers, text_rows, "text_fallback"

    return headers, rows, "row_per_table"


def _extract_with_pattern_set(page_texts: List[str]) -> List[List[str]]:
    """Try each regex in :data:`_TX_PATTERNS` in turn; the first pattern that
    matches at least one row wins. (The 'more rows than table extraction' gate
    is enforced by the caller, which only switches to text fallback when the
    pattern set out-counts the table extraction.)
    """
    combined = "\n".join(page_texts)
    for pat in _TX_PATTERNS:
        rows: List[List[str]] = []
        for m in pat.finditer(combined):
            tx_date = m.group(2)
            desc = m.group(3).strip()
            amount = m.group(4).strip()
            rows.append([tx_date, desc, amount])
        if rows:
            return rows
    return []


def _clip_preview(cells: List[str]) -> List[str]:
    """Wire-safety clamp: first PREVIEW_MAX_CELLS cells, each truncated to
    PREVIEW_CELL_CHAR_CAP chars. CSS does the visual layout separately
    (LOCKED IRIS-3 — visual cap is 160px ellipsis in StepPickTable).
    """
    return [
        (str(c) if c is not None else "")[:PREVIEW_CELL_CHAR_CAP]
        for c in (cells or [])[:PREVIEW_MAX_CELLS]
    ]


# ─── Public entry point ──────────────────────────────────────────────────────

def parse(raw_bytes: bytes, selected_table_index: Optional[int] = None, **_ignored) -> ParseResult:
    """Extract one transaction table from a PDF.

    Runs the pdfplumber extraction in a child process so that a malformed PDF
    cannot lock up the FastAPI worker. 30s wall-clock kill. On timeout the
    process is terminated and the client gets ``kind: parse_error``.

    When ``selected_table_index`` is given AND the strategy is ``standard``,
    the caller has chosen a specific candidate table; the rows/header come
    from that candidate. Otherwise the heuristic default (largest table) wins.
    """
    queue: "multiprocessing.Queue" = multiprocessing.Queue()
    proc = multiprocessing.Process(target=_extract_in_worker, args=(raw_bytes, queue))
    proc.start()
    proc.join(timeout=WORKER_TIMEOUT_SECONDS)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():  # pragma: no cover
            proc.kill()
            proc.join()
        log.warning("PDF parse timed out after %ss", WORKER_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": "PDF parsing timed out"},
        )

    try:
        kind, payload = queue.get_nowait()
    except Exception:
        # No payload — worker died before queueing anything.
        log.warning("PDF worker exited without payload (exitcode=%s)", proc.exitcode)
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": _GENERIC_PARSE_ERROR},
        )

    if kind == "error":
        status_code, message = payload
        # User-facing parse caps: 413 stays specific (size guidance), the rest
        # collapse to a generic kind=parse_error. Logging stays on the server.
        log.info("PDF rejected: %s", message)
        if status_code == 413:
            raise HTTPException(
                status_code=413,
                detail={"kind": "parse_error", "message": message},
            )
        raise HTTPException(
            status_code=status_code,
            detail={"kind": "parse_error", "message": message},
        )

    if kind == "exception":
        # § 7.5: log class name only unless DEBUG=true. Client gets the
        # generic message — never the underlying exception text (which may
        # contain extracted PDF content).
        if os.getenv("DEBUG", "false").lower() == "true":
            log.exception("PDF parse failed (class=%s)", payload)
        else:
            log.warning("PDF parse failed: %s", payload)
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": _GENERIC_PARSE_ERROR},
        )

    # kind == "ok"
    header, rows, candidates, strategy = payload

    # Apply user's table choice for the standard layout. Out-of-range index
    # is a client bug — surface as 400 rather than silently fall through.
    if (
        selected_table_index is not None
        and strategy == "standard"
        and candidates
    ):
        match = next((c for c in candidates if c.index == selected_table_index), None)
        if match is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "kind": "parse_error",
                    "message": f"selected_table_index {selected_table_index} out of range",
                },
            )
        header = match.header
        rows = match.rows
        chosen_index = match.index
    elif candidates and strategy == "standard":
        # Default: pick the largest candidate. Worker has already pre-set
        # header/rows to the largest table; this just records the index.
        largest = max(candidates, key=lambda c: c.row_count)
        chosen_index = largest.index
    else:
        # row_per_table / text_fallback: single synthetic candidate at index 0.
        chosen_index = 0

    # Re-check the row cap after a user selection (could pick a smaller table).
    if len(rows) > MAX_PDF_ROWS:
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": f"Table exceeds {MAX_PDF_ROWS}-row limit"},
        )

    return ParseResult(
        header=header,
        rows=rows,
        candidate_tables=candidates,
        selected_table_index=chosen_index,
        extraction_strategy=strategy,
    )
