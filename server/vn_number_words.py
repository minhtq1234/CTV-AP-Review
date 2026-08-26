"""Read a Vietnamese amount written in words back into an integer.

Vietnamese invoices print every total twice: once in digits and once spelled
out. On the Bảng Kê Thu Mua that redundancy is the only independent check we
have on the digit read — a single OCR slip in `240.305.556` would otherwise
turn criterion #20 into a false accusation against the roster.

Parsing runs on accent-folded, lowercased tokens, which is what makes this
survive OCR: Tesseract returned `trắm` for `trăm` and `đông).` for `đồng)` on
the real page, and both fold to the same key.
"""
from __future__ import annotations

import re

from ocr_extract import norm

#: Folded digit words. `mốt`, `tư` and `lăm` are the forms 1, 4 and 5 take
#: after `mươi` (hai mươi mốt = 21, hai mươi tư = 24, hai mươi lăm = 25).
_DIGITS = {
    "khong": 0, "mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5,
    "sau": 6, "bay": 7, "tam": 8, "chin": 9,
    "tu": 4, "lam": 5,
}

#: Scale words within a three-digit group.
_GROUP_SCALES = {"muoi": 10, "chuc": 10, "tram": 100}

#: Scale words that close a group and multiply it.
_BIG_SCALES = {
    "nghin": 1_000, "ngan": 1_000,
    "trieu": 1_000_000,
    "ty": 1_000_000_000, "ti": 1_000_000_000,
}

#: `lẻ` / `linh` mark a skipped tens place: ba trăm lẻ năm = 305.
_ZERO_FILLERS = {"le", "linh"}

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def parse_amount_words(text: str) -> int | None:
    """The amount `text` spells out, or None if it spells out no amount.

    Returns None rather than guessing: a lone scale word (`nghìn`) or a name
    carries no quantity, and inventing one would be worse than abstaining.
    """
    total = 0          # groups already closed by a big scale
    group = 0          # the three-digit group being built
    pending: int | None = None   # digit awaiting its scale, or standing alone
    saw_digit = False

    for raw in _TOKEN.findall(text):
        token = norm(raw)

        if token == "muoi":
            # `mười` (ten) with no preceding digit is 10, not a multiplier.
            group += (pending if pending is not None else 1) * 10
            pending = None
            saw_digit = True
            continue

        if token in _GROUP_SCALES:
            group += (pending if pending is not None else 1) * _GROUP_SCALES[token]
            pending = None
            saw_digit = True
            continue

        if token in _BIG_SCALES:
            if pending is not None:
                group += pending
                pending = None
            if not saw_digit and group == 0:
                continue        # a scale word with nothing to scale
            total += group * _BIG_SCALES[token]
            group = 0
            continue

        if token in _ZERO_FILLERS:
            if pending is not None:
                group += pending
                pending = None
            continue

        if token in _DIGITS:
            if pending is not None:      # two digits in a row: flush the first
                group += pending
            pending = _DIGITS[token]
            saw_digit = True
            continue

        # anything else -- currency, punctuation, stray words -- is ignored

    if pending is not None:
        group += pending
    if not saw_digit:
        return None
    return total + group
