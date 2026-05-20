"""
Shared dataclasses for parser results.

ParseResult.candidate_tables / selected_table_index / extraction_strategy are
PDF-specific and remain ``None`` for the CSV path. CandidateTable.header and
CandidateTable.rows are server-side only — they MUST NOT be serialised over
the wire (see schemas.CandidateTableSchema). LOCKED (MASON-2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional


ExtractionStrategy = Literal["standard", "row_per_table", "text_fallback"]


@dataclass
class CandidateTable:
    """One candidate transaction table extracted from a PDF.

    ``header`` and ``rows`` are kept server-side only; only ``index``,
    ``row_count``, ``column_count`` and ``first_row_preview`` are wire-exposed
    via :class:`schemas.CandidateTableSchema`.
    """
    index: int
    row_count: int
    column_count: int
    header: List[str]                  # server-side only
    rows: List[List[str]]              # server-side only
    first_row_preview: List[str] = field(default_factory=list)  # ≤5 cells, ≤80 chars each — wire-exposed


@dataclass
class ParseResult:
    """Common shape returned by every import parser."""
    header: List[str]
    rows: List[List[str]]
    candidate_tables: Optional[List[CandidateTable]] = None
    selected_table_index: Optional[int] = None
    extraction_strategy: Optional[ExtractionStrategy] = None
