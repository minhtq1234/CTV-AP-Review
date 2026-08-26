"""Read the Bảng Kê Thu Mua (mẫu 02/TNDN) — the batch-level purchase listing.

This document is the missing half of criterion #20. None of the three rosters
carries a total row, so an Excel-only check cannot run; the total is printed on
the last page of the listing instead. On the July submission that is
`240.305.556VNĐ`, which reconciles exactly with the sum of the roster's 41
Gross values.

IDP's `GET_TABLE` was tested on this form four times — as a 6-page PDF and as
upright single-page images, twice each. It classifies the form confidently once
rotation is corrected but returns zero rows every time, so the reading is done
here.

**The total is read twice.** Vietnamese invoices print every amount in digits
and again spelled out, and this module parses both and requires them to agree.
Without that, a single OCR slip in `240.305.556` would turn #20 into a false
accusation against the roster — the one failure mode this criterion must not
have.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ocr_extract import group_lines, norm, union_bbox
from vn_number_words import parse_amount_words

#: The `Tổng giá trị hàng hóa, dịch vụ mua vào:` label, accent-folded. Matched
#: on the line's folded text so OCR tone-mark damage does not lose the anchor.
_TOTAL_ANCHORS = ("tong gia tri hang hoa", "dich vu mua vao", "mua vao:")

#: `(Số tiền bằng chữ ...)` / `(Bằng chữ: ...)` — the spelled-out amount opens
#: after these two tokens. Compared on stripped, folded keys so `(Băng` and
#: `chữ:` both match.
_WORDS_MARKER = ("bang", "chu")

#: The line grouping the real page needs: the label cell wraps, and its words
#: sit up to ~21px apart vertically within one visual line.
_Y_TOL = 25

#: `\d{1,4}` not `\d{1,3}` for the leading group: Tesseract drops a separator
#: often enough that `8333.333` (really `8.333.333`) appears on real rows. In
#: vi-VN formatting `.` groups thousands and never marks a decimal, so reading
#: the whole token as one integer is the right call, not a guess.
_MONEY = re.compile(r"^(\d{1,4}(?:[.,]\d{3})+)\s*(?:vnd|vnđ|đ|d)?$")


def money_token(text: str) -> int | None:
    """The amount a single OCR token spells, or None if it is not money.

    Requires a group separator: `8.888.889` is money, `8888889` could be a
    quantity or an id. Tesseract sometimes drops one separator (`8333.333` for
    `8.333.333`), which still matches and still reads correctly.
    """
    cleaned = norm(text).strip().rstrip(".,;:")
    match = _MONEY.match(cleaned)
    if not match:
        return None
    return int(re.sub(r"[.,]", "", match.group(1)))


#: Characters Tesseract substitutes for digits, and what they may really be.
#: `§` for `8` is the one that actually broke a real page (February's
#: `25§.638.890`). Kept deliberately small: every extra entry widens the search
#: for a value that could be wrong.
_CONFUSIONS = {
    "§": "58", "s": "5", "S": "5", "$": "5",
    "o": "0", "O": "0", "Q": "0", "D": "0",
    "l": "1", "I": "1", "i": "1", "|": "1",
    "z": "2", "Z": "2",
    "b": "6", "G": "6",
    "t": "7", "T": "7", "?": "7",
    "B": "8",
    "g": "9", "q": "9",
    "a": "4", "A": "4",
}

#: How many damaged characters a repair will consider. Beyond this the token is
#: not OCR noise, it is unreadable, and guessing would be inventing money.
_MAX_REPAIRS = 3


def digit_repairs(text: str) -> set[int]:
    """Every amount `text` could be, if some characters are OCR substitutions.

    A repair is never trusted on its own — `read_total` only accepts one that
    reproduces the spelled-out amount exactly, so the words stay the authority.
    """
    core = re.sub(r"(?i)\s*(?:vnd|vnđ|đ)$", "", text.strip()).rstrip(".,;:")
    damaged = [i for i, ch in enumerate(core)
               if ch in _CONFUSIONS and ch not in ".,"]
    if len(damaged) > _MAX_REPAIRS:
        return set()

    found: set[int] = set()
    for mask in range(1 << len(damaged)):
        for combo in _substitutions(core, damaged, mask):
            amount = money_token(combo)
            if amount is not None:
                found.add(amount)
    return found


def _substitutions(core: str, damaged: list[int], mask: int) -> list[str]:
    """`core` with the characters selected by `mask` replaced, all ways."""
    variants = [core]
    for bit, index in enumerate(damaged):
        if not mask & (1 << bit):
            continue
        variants = [
            v[:index] + replacement + v[index + 1:]
            for v in variants
            for replacement in _CONFUSIONS[core[index]]
        ]
    return variants


@dataclass(frozen=True)
class TotalRead:
    """The listing's printed total, and how much to trust it.

    `amount` is set only when the two reads agree, or when only one of them is
    printed. On disagreement it stays None and `reason` says so, so #20 abstains
    rather than accuses.
    """

    amount: int | None
    digits: int | None
    words: int | None
    reason: str
    page: int | None = None
    confidence: float = 0.0
    bbox: dict | None = None
    #: True when the digits only matched the words after repairing an OCR
    #: substitution. Trust is unchanged (two sources still agree) but the UI
    #: should say the printed digits were damaged.
    digits_repaired: bool = False

    @property
    def corroborated(self) -> bool:
        return self.reason == "digits-and-words-agree"


#: How much a read is worth, best first. The table's own column header reads
#: `Hàng hóa, dịch vụ mua vào` -- the same phrase as the total label -- so
#: anchoring cannot be the whole test: the header matched on page 3 of the real
#: submission and masked the total on page 8. Every anchored line is read and
#: the best one wins, which makes an amount-less match harmless.
_READ_RANK = {
    "digits-and-words-agree": 0,
    "digits-and-words-disagree": 1,
    "digits-only": 2,
    "words-only": 3,
}


def read_total(words_by_page: dict[int, list[dict]]) -> TotalRead:
    """Find and read the listing's total across `{page_index: ocr words}`.

    Reads every line whose text carries the total label and returns the most
    trustworthy of them; a label with no amount beside it is not a total.
    """
    reads = [
        _read_line(line, page, words_by_page[page])
        for page in sorted(words_by_page)
        for line in group_lines(words_by_page[page], y_tol=_Y_TOL)
        if _is_total_line(line)
    ]
    candidates = [r for r in reads if r.reason in _READ_RANK]
    if not candidates:
        return TotalRead(None, None, None, "not-found")
    return min(candidates, key=lambda r: (_READ_RANK[r.reason], r.page or 0))


def _is_total_line(line: list[dict]) -> bool:
    text = norm(" ".join(w["text"] for w in line))
    return any(anchor in text for anchor in _TOTAL_ANCHORS)


def _read_line(line: list[dict], page: int, page_words: list[dict]) -> TotalRead:
    digits, money_words = _first_money(line)
    words = _spelled_amount(line, page_words)
    repaired = False

    if digits is None and words is not None:
        digits, money_words, repaired = _repair(line, words)
        if digits is None:
            damaged = _damaged_money(line)
            if damaged is not None:
                # A money-shaped token sits on the line but nothing it could be
                # matches the words. Accepting the words alone here would hide a
                # contradiction printed on the page.
                return TotalRead(
                    None, None, words, "digits-and-words-disagree", page,
                    _confidence([damaged]), union_bbox([damaged]),
                )

    if digits is not None and words is not None:
        agree = digits == words
        return TotalRead(
            digits if agree else None, digits, words,
            "digits-and-words-agree" if agree else "digits-and-words-disagree",
            page, _confidence(money_words), union_bbox(money_words),
            digits_repaired=repaired and agree,
        )
    if digits is not None:
        return TotalRead(digits, digits, None, "digits-only", page,
                         _confidence(money_words), union_bbox(money_words))
    if words is not None:
        return TotalRead(words, None, words, "words-only", page,
                         _confidence(line), None)
    # An anchored line with no amount either way: the column header, or a
    # label whose number OCR lost. `_READ_RANK` filters these out.
    return TotalRead(None, None, None, "no-amount-on-the-line", page)


def _repair(line: list[dict], words: int) -> tuple[int | None, list[dict], bool]:
    """The damaged money token on `line` that repairs to `words`, if any."""
    for word in line:
        if words in digit_repairs(word["text"]):
            return words, [word], True
    return None, [], False


def _damaged_money(line: list[dict]) -> dict | None:
    """A token that is clearly meant to be money but does not parse."""
    for word in line:
        text = word["text"]
        if (any(ch.isdigit() for ch in text)
                and any(sep in text for sep in ".,")
                and money_token(text) is None):
            return word
    return None


def _first_money(line: list[dict]) -> tuple[int | None, list[dict]]:
    for word in line:
        amount = money_token(word["text"])
        if amount is not None:
            return amount, [word]
    return None, []


def _spelled_amount(line: list[dict], page_words: list[dict]) -> int | None:
    """The `(… bằng chữ …)` amount, read from the marker up to the closing `)`.

    Scoped deliberately: `năm` is both "five" and "year", and the preparer's
    name sits further down the page, so reading past the `)` would fold stray
    number words into the amount.

    Works on tokens rather than character offsets — accent folding is not
    guaranteed to preserve string length, so indexing a folded position back
    into the raw text was fragile.
    """
    tokens = [w["text"] for w in line]
    if not _marker_at(tokens) or ")" not in " ".join(tokens):
        tokens += _continuation(line, page_words)
    start = _marker_at(tokens)
    if start is None:
        return None
    tail = tokens[start + len(_WORDS_MARKER):]
    scoped: list[str] = []
    for token in tail:
        if ")" in token:
            scoped.append(token.split(")")[0])
            break
        scoped.append(token)
    return parse_amount_words(" ".join(scoped))


def _marker_at(tokens: list[str]) -> int | None:
    """Index of the `bằng chữ` marker in `tokens`, or None."""
    keys = [_key(token) for token in tokens]
    for i in range(len(keys) - len(_WORDS_MARKER) + 1):
        if tuple(keys[i:i + len(_WORDS_MARKER)]) == _WORDS_MARKER:
            return i
    return None


def _key(token: str) -> str:
    """A token stripped to its folded letters, for marker matching."""
    return re.sub(r"[^\w]", "", norm(token), flags=re.UNICODE)


#: How many lines below the label to follow a wrapped amount cell. Three, not
#: one: on the real page a table rule is read as a lone `-` word between the
#: two halves of the cell, so the very next line is not the continuation.
_MAX_CONTINUATION_LINES = 3


def _continuation(line: list[dict], page_words: list[dict]) -> list[str]:
    """Tokens from the lines below `line`, up to and including the closing `)`."""
    below = max(w["y"] for w in line)
    following = [
        candidate for candidate in group_lines(page_words, y_tol=_Y_TOL)
        if min(w["y"] for w in candidate) > below
    ]
    collected: list[str] = []
    for candidate in following[:_MAX_CONTINUATION_LINES]:
        tokens = [word["text"] for word in candidate]
        collected += tokens
        if any(")" in token for token in tokens):
            break
    return collected


def _confidence(words: list[dict]) -> float:
    if not words:
        return 0.0
    return sum(w["conf"] for w in words) / len(words)
