"""
Procedurally-generated PDF fixtures for the Option B PDF parser tests.

Each generator returns a ``bytes`` payload — fixtures are NOT written to
disk, so there is no risk of committing real bank statements. All content
is generic placeholder text:

* placeholder merchants ("Coffee Co", "Office Supplies", etc.)
* generic descriptions ("Test row 1", "Test row 2", etc.)
* random round amounts in cents

reportlab is a dev-only dependency (see backend/requirements-dev.txt) and
is never available in the runtime image — these helpers must only be
imported from tests.
"""
from __future__ import annotations

import io
from typing import List, Optional


def _ensure_reportlab():
    try:
        from reportlab.lib import colors  # noqa: F401
        from reportlab.lib.pagesizes import LETTER  # noqa: F401
        from reportlab.lib.styles import getSampleStyleSheet  # noqa: F401
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak  # noqa: F401
    except ImportError as exc:  # pragma: no cover — surfaces in dev install
        raise RuntimeError(
            "reportlab is required for PDF fixture generation. "
            "Install via: pip install -r backend/requirements-dev.txt"
        ) from exc


def _build(elements) -> bytes:
    """Render a flowables list to PDF bytes."""
    _ensure_reportlab()
    from reportlab.lib.pagesizes import LETTER
    from reportlab.platypus import SimpleDocTemplate
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    doc.build(elements)
    return buf.getvalue()


def _gridded(data):
    """Wrap rows in a Table with a black grid — pdfplumber's default table
    detector keys off visible strokes; without them every table comes back
    empty. Style kept in one helper so all fixtures share it.
    """
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    t = Table(data)
    t.setStyle(TableStyle([
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0),  colors.lightgrey),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def standard_layout_pdf() -> bytes:
    """Two-page PDF with a small summary table followed by a transactions
    table. Used to verify largest-table selection and the standard strategy.
    """
    from reportlab.platypus import Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = []

    # Summary table — small (1 data row), should NOT be picked.
    elements.append(Paragraph("Summary", styles["Heading2"]))
    summary = [
        ["Opening", "Closing", "Period"],
        ["100.00", "250.00", "2026-01"],
    ]
    elements.append(_gridded(summary))
    elements.append(Spacer(1, 18))

    # Transactions table — multi-row, the one we expect to win.
    elements.append(Paragraph("Transactions", styles["Heading2"]))
    txns = [
        ["Date", "Description", "Amount"],
        ["2026-01-02", "Coffee Co",        "-4.50"],
        ["2026-01-03", "Office Supplies",  "-23.10"],
        ["2026-01-04", "Salary placeholder", "1200.00"],
        ["2026-01-05", "Test merchant A",  "-9.99"],
    ]
    elements.append(_gridded(txns))
    elements.append(PageBreak())

    # Second-page continuation — same header row, different data.
    elements.append(Paragraph("Transactions (cont.)", styles["Heading2"]))
    cont = [
        ["Date", "Description", "Amount"],
        ["2026-01-06", "Test merchant B", "-12.00"],
        ["2026-01-07", "Test merchant C", "-7.25"],
    ]
    elements.append(_gridded(cont))
    return _build(elements)


def row_per_table_pdf(num_rows: int = 6) -> bytes:
    """Synthesise a row-per-table layout — each transaction is its own
    1-row table. Detected by the heuristic and flattened.
    """
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = [Paragraph("Statement", styles["Heading2"])]

    # Each "transaction" = its own one-row table. Header repeats so the
    # parser can identify it as the most-frequent row.
    header_row = ["Date", "Description", "Amount"]
    for i in range(num_rows):
        elements.append(_gridded([header_row]))
        elements.append(Spacer(1, 2))
        elements.append(_gridded([[f"2026-02-{i+1:02d}", f"Test row {i+1}", f"-{(i+1)*10}.00"]]))
        elements.append(Spacer(1, 4))
    return _build(elements)


def two_date_text_fallback_pdf() -> bytes:
    """Row-per-table layout where the header has TWO date columns and the
    transaction lines are also present as plain text in a Cr/Dr shape that
    triggers regex pattern (a). Designed so the text fallback finds more
    rows than the table extraction (the row-per-table tables only hold the
    header line; the data is text-only).
    """
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = [Paragraph("Statement (text-fallback fixture)", styles["Heading2"])]

    # Repeat the header as the most-frequent row-per-table row (≥4× so the
    # row-per-table heuristic fires).
    header_row = ["Processed Date", "Transaction Date", "Description", "Amount"]
    for _ in range(6):
        elements.append(_gridded([header_row]))
        elements.append(Spacer(1, 4))

    # Now add the transaction lines as plain text. Cr/Dr suffix triggers
    # pattern (a) of the regex set.
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("Detail:", styles["Heading4"]))
    for i in range(5):
        elements.append(Paragraph(
            f"01/03/26 02/03/26 Test merchant {i+1} $50.0{i} Cr",
            styles["BodyText"],
        ))
    return _build(elements)


def multi_candidate_pdf() -> bytes:
    """Three differently-shaped multi-row tables on a single page — each with
    a distinct header so the auto-merge logic leaves them as three separate
    candidates. Used to verify that all candidates surface and that the
    largest wins by default. (Same-header tables are merged into one
    candidate by design — see ``multi_page_same_header_pdf`` for that case.)
    """
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = []

    # Table 1 — 3 data rows.
    elements.append(Paragraph("Table A", styles["Heading3"]))
    elements.append(_gridded([
        ["Date", "Description", "Amount"],
        ["2026-04-01", "Alpha placeholder", "-5.00"],
        ["2026-04-02", "Beta placeholder",  "-6.00"],
        ["2026-04-03", "Gamma placeholder", "-7.00"],
    ]))
    elements.append(Spacer(1, 16))

    # Table 2 — 4 data rows, distinct header (this should win as largest).
    elements.append(Paragraph("Table B", styles["Heading3"]))
    elements.append(_gridded([
        ["Posted", "Memo", "Value"],
        ["2026-04-04", "Delta placeholder",   "-1.00"],
        ["2026-04-05", "Epsilon placeholder", "-2.00"],
        ["2026-04-06", "Zeta placeholder",    "-3.00"],
        ["2026-04-07", "Eta placeholder",     "-4.00"],
    ]))
    elements.append(Spacer(1, 16))

    # Table 3 — 2 data rows, distinct header.
    elements.append(Paragraph("Table C", styles["Heading3"]))
    elements.append(_gridded([
        ["When", "Detail", "Net"],
        ["2026-04-08", "Theta placeholder", "-8.00"],
        ["2026-04-09", "Iota placeholder",  "-9.00"],
    ]))
    return _build(elements)


def no_tables_pdf() -> bytes:
    """PDF with text only — no table structures."""
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements = [
        Paragraph("This PDF deliberately contains no extractable tables.", styles["Heading2"]),
        Spacer(1, 24),
        Paragraph("Some prose to fill the page.", styles["BodyText"]),
        Paragraph("None of this is structured.", styles["BodyText"]),
    ]
    return _build(elements)


def multi_page_same_header_pdf() -> bytes:
    """Three-page PDF where every page carries an identical 3-column header
    ("Date", "Description", "Amount") and disjoint data rows: 5 on page 1,
    4 on page 2, 3 on page 3. Used to verify the v1.3.2 auto-merge behaviour
    — pdfplumber surfaces three separate tables; the parser must re-stitch
    them into one candidate with 12 data rows.
    """
    from reportlab.platypus import Paragraph, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = []

    header_row = ["Date", "Description", "Amount"]
    pages_data = [
        # Page 1 — 5 rows
        [
            ["2026-06-01", "Test row A1", "-10.00"],
            ["2026-06-02", "Test row A2", "-11.00"],
            ["2026-06-03", "Test row A3", "-12.00"],
            ["2026-06-04", "Test row A4", "-13.00"],
            ["2026-06-05", "Test row A5", "-14.00"],
        ],
        # Page 2 — 4 rows
        [
            ["2026-06-06", "Test row B1", "-20.00"],
            ["2026-06-07", "Test row B2", "-21.00"],
            ["2026-06-08", "Test row B3", "-22.00"],
            ["2026-06-09", "Test row B4", "-23.00"],
        ],
        # Page 3 — 3 rows
        [
            ["2026-06-10", "Test row C1", "-30.00"],
            ["2026-06-11", "Test row C2", "-31.00"],
            ["2026-06-12", "Test row C3", "-32.00"],
        ],
    ]
    for i, data in enumerate(pages_data):
        elements.append(Paragraph(f"Transactions page {i + 1}", styles["Heading3"]))
        elements.append(_gridded([header_row] + data))
        if i < len(pages_data) - 1:
            elements.append(PageBreak())
    return _build(elements)


def different_headers_two_page_pdf() -> bytes:
    """Two-page PDF with two distinct-header tables — page 1 has
    ["Date", "Description", "Amount"] and page 2 has ["Posted", "Memo", "Value"].
    Asserts the merge logic does NOT false-positive across different headers.
    """
    from reportlab.platypus import Paragraph, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = []

    elements.append(Paragraph("Table one", styles["Heading3"]))
    elements.append(_gridded([
        ["Date", "Description", "Amount"],
        ["2026-07-01", "Test merchant alpha", "-5.00"],
        ["2026-07-02", "Test merchant beta", "-6.00"],
    ]))
    elements.append(PageBreak())

    elements.append(Paragraph("Table two", styles["Heading3"]))
    elements.append(_gridded([
        ["Posted", "Memo", "Value"],
        ["2026-07-03", "Test memo one", "-7.00"],
        ["2026-07-04", "Test memo two", "-8.00"],
        ["2026-07-05", "Test memo three", "-9.00"],
    ]))
    return _build(elements)


def au_credit_card_text_pdf() -> bytes:
    """3-column AU credit-card-style PDF — DD/MM/YY dates and Cr/Dr suffix
    amounts. Used to verify _normalise_amount + _normalise_date end-to-end
    through the wizard. Header + 3 data rows. Generic placeholder text only.
    """
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = [Paragraph("Card statement (test fixture)", styles["Heading2"])]
    elements.append(Spacer(1, 10))

    txns = [
        ["Date", "Description", "Amount"],
        ["20/04/26", "Interest Charged",       "$48.56 Dr"],
        ["28/03/26", "BPAY Payment Generic",   "$215.00 Cr"],
        ["12/04/26", "Test Purchase",          "$220.00 Cr"],
    ]
    elements.append(_gridded(txns))
    return _build(elements)


def oversized_page_count_pdf(pages: int) -> bytes:
    """PDF with the given number of pages — used to assert the MAX_PDF_PAGES cap.
    Each page has a trivial single-row table to keep the file size sane.
    """
    from reportlab.platypus import Paragraph, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    elements: list = []
    for i in range(pages):
        elements.append(Paragraph(f"Page {i+1}", styles["Heading3"]))
        elements.append(_gridded([["a", "b", "c"], ["1", "2", "3"]]))
        if i < pages - 1:
            elements.append(PageBreak())
    return _build(elements)
