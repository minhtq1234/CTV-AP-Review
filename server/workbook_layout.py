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
from ocr_extract import norm

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


#: What an image column can hold. `card` is the only kind the pipeline consumes
#: today; `bank` and `tax` are recognised so they are never mistaken for a card
#: side, and are available to the criteria that will want them (#8, #6).
CARD, BANK, TAX = "card", "bank", "tax"

_CARD_HEADERS = ("hinh cccd", "anh cccd", "hinh the")
_ANY_IMAGE_HEADERS = ("hinh anh", "hinh", "anh")


def classify_image_columns(header: dict[int, str], sheet_name: str) -> dict[int, str]:
    """Column index -> what kind of image it holds, read from the header row.

    A merged header cell reports the same text for every column it spans, which
    is what tells us `Hình CCCD` over D:E means front and back rather than one
    image. A generic `Hình Ảnh` takes its meaning from its neighbour: beside a
    `STK` column it is a bank screenshot; on a sheet keyed by MST it is a tax
    lookup. Anything unrecognised is left out rather than guessed at -- an
    unclassified image is better than an image filed as the wrong kind.
    """
    flat = {index: norm(str(text or "")) for index, text in header.items()}
    kinds: dict[int, str] = {}
    for index, text in flat.items():
        if not text:
            continue
        if any(marker in text for marker in _CARD_HEADERS):
            kinds[index] = CARD
            continue
        if any(marker in text for marker in _ANY_IMAGE_HEADERS):
            left = flat.get(index - 1, "")
            if "stk" in left or "tai khoan" in left:
                kinds[index] = BANK
            elif "mst" in norm(sheet_name) or "mst" in left:
                kinds[index] = TAX
    return kinds


def column_letter(index: int) -> str:
    """0-based column index to its spreadsheet letter, so the declaration names
    columns the way the reviewer sees them in Excel."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters
