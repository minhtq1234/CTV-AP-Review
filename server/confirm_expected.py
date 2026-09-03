"""Is the value the bảng kê expects actually printed on this document?

Every criterion here already knows the answer it is looking for -- the bảng kê
states it -- so none of them has to *discover* a value on the page. Confirming
a known one is a search, and a search is both easier and safer than extraction.

Two mechanisms, and they are deliberately not one
-------------------------------------------------
Names and numbers fail differently, so the safe answer differs.

**`confirm_name` -- the whole document, fuzzy.** A name cannot be discovered at
all: it has no shape a pattern can match (`ocr_extract.FIELD_SPECS`' `hoten` is
the one entry with `"patterns": []`), and on a real contract it often carries no
label saying whose it is. But a *specific* name cannot collide. Measured across
the 79 distinct names on disk, the highest score between two different people is
**0.81**, and no pair of different people reaches 0.90 -- while the expected name
scored **1.00** on all 9 document-packet pairs of case `935e37e5`. So a threshold
at 0.90 separates cleanly, and searching for one known name is safe where
"find any name" is not.

**`confirm_at_label` -- one label's neighbourhood, exact.** Two restrictions,
each answering a different way this could confirm a lie.

*Anchored*, because across **564 roster rows on disk `cccd == mst` in 564 of
them** -- a Vietnamese personal tax code is the citizen's ID number. A
free-floating search for the expected MST would land on the CCCD occurrence and
report a confirmation that means nothing.

*Exact*, because this exists to tell a misread from a real disagreement, and a
fuzzy matcher cannot: `001100000004` against an expected `001100000001` is one
character in twelve, which `SequenceMatcher` scores **0.917** -- over the 0.90
that is right for names. Fuzzy here would confirm the very numbers it is meant
to distinguish, so digits are compared digit for digit.

What this must never do
-----------------------
`confirm_at_label` returning a hit means "the expected digits are printed at
this label". It is evidence that the reader misread, **not** grounds to call the
paperwork correct: nothing here may promote a cell to `Đạt`. The bảng kê is what
is being audited, so letting it certify itself inverts the tool. `evaluate` uses
a hit to turn a `no` into an `rv` that names the misread, and for nothing else.

On reuse
--------
`semantic_read.locate_quote` already does whole-document fuzzy location and was
measured at 100% on verbatim text, but it cannot serve either function here.
It refuses anything under `MIN_WORDS = 6` -- for the measured reason that a
short quote lands on the wrong occurrence of itself -- and a Vietnamese name is
three or four words. Its threshold is also `semantic_read.MIN_RATIO`, which is
about boxing a model's quote; tying a name check to it would let one move
silently with the other. So this reuses the parts that are the same job --
`fold` (two-sided folding, measured) and `_index` (the fiddly token/span/box
mapping) -- and keeps its own thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from compare_values import _digits
from semantic_read import _index, fold

#: A name confirms at or above this. Measured across the 79 distinct names on
#: disk: no two different people reach it (highest 0.81), and a real hit scores
#: 1.00. It is a false-positive control, not a tuning knob -- lowering it starts
#: confirming one person's name against another's.
MIN_NAME_RATIO = 0.90

#: How far a window may differ in token count from the expected name's own, so
#: OCR splitting or joining a syllable is still reachable. Same slack
#: `semantic_read.WIDTH_SLACK` uses, and safe for the same reason: a window
#: longer or shorter than the name can only score *lower* against it, so the
#: measured 0.81 ceiling between two people is not raised by widening the sweep.
WIDTH_SLACK = 2

#: How many words after a label's last word count as its neighbourhood. Wide
#: enough for a label followed by a colon and a CCCD split into four groups
#: (`0011 0000 0001`), tight enough not to reach the next field's value. Only
#: forwards: Vietnamese forms print the value after the label, and reaching
#: backwards would pick up the previous field's.
NEIGHBOURHOOD_WORDS = 8


@dataclass(frozen=True)
class Hit:
    """Where an expected value was confirmed, and how strong the match is.

    `start` and `end` are inclusive indices into the words that were searched,
    so a caller holding word boxes can `ocr_extract.union_bbox` the span and
    point a reviewer at it.
    """

    score: float
    start: int
    end: int


def _tokens(words) -> list[dict]:
    """The given words as `_index` tokens, accepting plain strings or boxes.

    Callers at read time hold `{text, x, y, w, h, conf}` word dicts; a test (and
    anything working from recorded text) holds strings. Both are the same search.
    """
    return [{"text": w} if isinstance(w, str) else w for w in words]


def confirm_name(expected: str, words) -> Hit | None:
    """The best place `expected` appears among `words`, at or above 0.90.

    `None` when it is not there -- and, deliberately, when `expected` is empty:
    a packet that matched no roster row has nothing to confirm, and falling back
    to "find any name" is the discovery problem this exists to avoid.
    """
    wanted = fold(expected)
    if not wanted:
        return None
    tokens = _tokens(words)
    text, spans, kept = _index(tokens)
    if not spans:
        return None

    width_wanted = len(wanted.split())
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(wanted)
    best: Hit | None = None
    for width in range(max(1, width_wanted - WIDTH_SLACK),
                       width_wanted + WIDTH_SLACK + 1):
        if width > len(spans):
            break
        for start in range(len(spans) - width + 1):
            candidate = text[spans[start][0]:spans[start + width - 1][1]]
            matcher.set_seq1(candidate)
            # Cheap upper bounds on ratio; skipping on them is what keeps a
            # whole-document sweep affordable.
            if matcher.real_quick_ratio() < MIN_NAME_RATIO:
                continue
            if matcher.quick_ratio() < MIN_NAME_RATIO:
                continue
            score = matcher.ratio()
            if score >= MIN_NAME_RATIO and (best is None or score > best.score):
                best = Hit(score, kept[start], kept[start + width - 1])
    return best


def _label_ends(text: str, spans: list[tuple[int, int]],
                anchors) -> list[int]:
    """Token position just past each occurrence of any of `anchors`.

    Matched against the folded page text rather than token by token, so a label
    OCR split across words (`Mã số thuế thu nhập cá nhân`) or joined into one
    still anchors.
    """
    ends: list[int] = []
    for anchor in anchors:
        folded = fold(anchor)
        if not folded:
            continue
        at = text.find(folded)
        while at >= 0:
            stop = at + len(folded)
            after = [i for i, (s, _) in enumerate(spans) if s >= stop]
            if after:
                ends.append(after[0])
            at = text.find(folded, at + 1)
    return sorted(set(ends))


def confirm_at_label(expected: str, words, anchors) -> Hit | None:
    """Whether `expected` is printed at one of `anchors`, among `words`.

    Exact, never fuzzy -- see the module docstring: one wrong digit in twelve
    scores 0.917, so a fuzzy match here would confirm exactly the misreads this
    is built to name. Digits are compared digit for digit, which also makes it
    indifferent to OCR splitting a number into groups.

    A hit says the expected value IS printed at that label. It never says the
    paperwork is correct.
    """
    if not expected.strip():
        return None
    tokens = _tokens(words)
    text, spans, kept = _index(tokens)
    if not spans:
        return None

    wanted_digits = _digits(expected)
    wanted_text = fold(expected)

    for end in _label_ends(text, spans, anchors):
        limit = min(len(spans), end + NEIGHBOURHOOD_WORDS)
        # Every contiguous run within the neighbourhood, so a number the page
        # broke into groups rejoins while a longer run stays a different number.
        for start in range(end, limit):
            for last in range(start, limit):
                span = [text[spans[i][0]:spans[i][1]]
                        for i in range(start, last + 1)]
                joined = " ".join(span)
                if wanted_digits:
                    if _digits(joined) == wanted_digits:
                        return Hit(1.0, kept[start], kept[last])
                elif joined == wanted_text:
                    return Hit(1.0, kept[start], kept[last])
    return None
