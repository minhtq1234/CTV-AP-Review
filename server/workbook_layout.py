"""Which sheet is the bảng kê, and which columns hold which images.

Both answers come from the sheet's own headers rather than from a per-template
declaration. `roster_checks.locate_columns` already reads two different
templates unaided; this applies the same idea to the two things it does not
cover -- choosing a sheet in a multi-sheet workbook, and finding the image
columns.

Pure: takes rows and header values, returns decisions. No openpyxl objects
cross these signatures, so every branch is testable without a file.
"""
from __future__ import annotations

import roster_checks

#: A sheet has to carry these to be usable as a bảng kê at all. Without a name
#: there is nobody to match a packet to; without a CCCD there is no identity to
#: match on; without a money column there is nothing to pay.
REQUIRED_COLUMNS = ("name", "cccd")
MONEY_COLUMNS = ("gross", "net", "pit")


def score_roster_sheet(rows: list[list]) -> int:
    """How much like a bảng kê this sheet looks, as a count of mapped columns.

    Deliberately a plain count rather than a weighted rule: the sheet that maps
    the most known columns is the roster, and every template we have seen makes
    that unambiguous by a wide margin (the PUBGm `CTV` sheet maps 13; its
    `CCCD` and `MST` sheets map 3 each).
    """
    try:
        columns, _ = roster_checks.locate_columns(rows)
    except Exception:
        return 0
    return len(columns or {})


def select_roster_sheet(sheets: dict[str, list[list]]) -> str | None:
    """The name of the sheet to read as the bảng kê, or None if none qualifies.

    Ties break on workbook order, which is the order `sheets` is given in.
    """
    best_name, best_score = None, 0
    for name, rows in sheets.items():
        score = score_roster_sheet(rows)
        if score > best_score:
            best_name, best_score = name, score
    if best_name is None:
        return None
    columns, _ = roster_checks.locate_columns(sheets[best_name])
    if not all(key in (columns or {}) for key in REQUIRED_COLUMNS):
        return None
    return best_name


def missing_required_columns(rows: list[list]) -> list[str]:
    """Which of the columns nothing works without are absent from this sheet.

    Returns `["money"]` for the money group rather than naming all three, since
    a template only needs one of them.
    """
    columns, _ = roster_checks.locate_columns(rows)
    columns = columns or {}
    missing = [key for key in REQUIRED_COLUMNS if key not in columns]
    if not any(key in columns for key in MONEY_COLUMNS):
        missing.append("money")
    return missing
