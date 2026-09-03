"""Find each party's signature block on a document, during the read.

Five criteria (#21-#25) ask whether a document is signed and stamped. They are
answered by a person, but the tool's whole premise is that it points first --
and until now their evidence was built with page 0 and no box
(`evaluate.py`'s `_presence`), so it pointed at the top of the first page of
whatever document, which is to say nowhere.

Locating has to happen here rather than at check time: the saved manifest keeps
only `{src, width, height}` per page, so by the time a criterion is evaluated
there are no words left to search.

Nothing here decides a verdict. A presence criterion still resolves to REVIEW
for a person to answer; this only tells them where to look.
"""
from __future__ import annotations

from ocr_extract import _anchor_word_span, group_lines, norm, union_bbox

#: Folded phrase -> which party's block it heads.
#:
#: `ben cung ung dich vu` and not `cung cap`: the corpus says *cung ứng*, which
#: is what `ocr_extract._PARTY_B_HEADER` already learned and what the field
#: extractor anchors `hoten` on.
#:
#: `dai dien ben b` and not bare `ben b`: `Bên B` occurs throughout the prose of
#: a real BBNT, so the bare form matches body text and, being assigned last,
#: overwrites the real header.
_PHRASES = {
    norm("Bên Cung Ứng Dịch Vụ"): "ctv",
    norm("Đại diện Bên B"): "ctv",
    norm("Bên Sử Dụng Dịch Vụ"): "vng",
    norm("Đại diện Bên A"): "vng",
    norm("Đại diện VNG"): "vng",
}

#: How many line-heights below its header the signing space runs. Measured on
#: real contracts: the header sits ~8.4-9.1 line-heights above the printed name
#: under the signature, so a smaller multiple crops the name -- the very thing a
#: reviewer is checking -- out of the box.
_BLOCK_LINES = 9


def find_anchors(
    pages: dict[int, list[dict]],
    page_heights: dict[int, int] | None = None,
) -> dict[str, dict]:
    """`{party: {"page": int, "bbox": {...}}}` for one document.

    `pages` is one document's entry from `words_by_doc`, i.e. page index within
    the document -> its words. The page cannot come from a word: a word is
    `{text, x, y, w, h, conf}` and has never carried one. Reading `page` off a
    word yields 0 for every anchor, which is precisely the defect this exists to
    remove.

    Later hits win, and pages are walked in order and lines in reading order, so
    "later" means further down the document. That matters: a phrase can occur
    several times on one page (five times, on one real contract) and only the
    last is the signature header rather than a mention in the body.
    """
    found: dict[str, dict] = {}
    for page, words in sorted(pages.items()):
        for line in group_lines(words):
            for phrase, party in _PHRASES.items():
                covered = _anchor_word_span(line, phrase)
                if not covered:
                    continue
                box = union_bbox([line[index] for index in covered])
                box["height"] *= _BLOCK_LINES
                limit = (page_heights or {}).get(page)
                if limit:
                    box["height"] = max(0, min(box["height"], limit - box["y"]))
                found[party] = {"page": page, "bbox": box}
    return found
