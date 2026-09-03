"""Turn a quoted sentence into a place on the page, during the read.

Six criteria (#8, #9, #10, #11, #13) need a clause read rather than a pattern
matched. However they are read, the answer is worthless unless the reviewer can
check it: a value with nothing to verify against converts a `?` into an
unfalsifiable claim. So every extracted value has to carry a verbatim quote,
and this is what turns that quote into a box.

Locating happens here, at read time, for the same reason `signature_anchors`
does it: the saved manifest keeps only `{src, width, height}` per page, so by
the time a criterion is evaluated there are no words left to search.

Why this is not `signature_anchors.find_anchors`
------------------------------------------------
That answers "where does each party sign?" -- five phrases fixed at import, and
a box deliberately expanded to nine line-heights so it encloses the header, the
signature and the printed name. This answers "where is this exact sentence?" --
an arbitrary runtime string, the quote's own extent, no expansion. The height
multiplication is the whole point of one and would be a defect in the other.
Both reuse `ocr_extract`'s `norm`, `group_lines` and `union_bbox`.

Four things measured on 12 real contracts, each of which decides a line here
---------------------------------------------------------------------------
1. **Whole document, not per line.** A clause crosses a line break ~60% of the
   time at twelve words. Searching line by line -- what every existing
   `_anchor_word_span` caller does -- located **0.0%** of cross-line quotes,
   at both eight and twelve words, over 406 samples. Not "fewer": none.
2. **Whitespace collapsed.** A model handed `_page_text` sees a newline at
   every line end and may quote it back, and `norm` leaves it in place.
3. **Punctuation folded to a space on both sides.** A model normalising a
   comma, or hyphenating a word the page does not, otherwise misses entirely.
4. **A fuzzy fallback at 0.90, not 0.85.** Exact matching is fatally brittle:
   one changed character makes a verbatim matcher 0%. Measured on contiguous
   twelve-word quotes -- verbatim 100% located and 100% *exact*, one changed
   character 100%, one dropped word 93.3%, and the locator never once returned
   a page other than the source across 5,000+ quotes. The threshold is a
   false-positive control rather than a tuning knob: 0.85 boxes a foreign
   quote, 0.90 does not. One call costs ~0.01s on a 250-word page.

Two traps in measuring this, both of which cost real time
---------------------------------------------------------
Sampling "cross-line" quotes by joining the tail of one `group_lines` line to
the head of the next, having *filtered out* one-word lines, manufactures quotes
that are not contiguous on the page at all -- a skipped line still sits between
the halves in reading order. That understated this function at 71% when it
scores 100%, twice, in two independent harnesses. Cut quotes out of the folded
page text itself. And measuring the fuzzy path over a whole matrix is slow
enough to look hung: it is thousands of calls, not one slow call.

`MIN_WORDS` is the other half of that control. Below about six words a quote
lands on the wrong occurrence of itself (7.2% at four words), so a short quote
is refused rather than boxed. The prompt's job is to ask for the containing
clause, not the bare value -- #13's `term` and `account` parts invite exactly
the short quotes this refuses.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ocr_extract import group_lines, norm, union_bbox

#: Below this many words a quote is refused rather than located.
MIN_WORDS = 6

#: Minimum SequenceMatcher ratio for the fuzzy fallback.
MIN_RATIO = 0.90

#: How far a fuzzy window may differ in length from the quote's own token
#: count, so a dropped or added word is still reachable. A window free to grow
#: would match a whole paragraph containing the quote and box all of it.
WIDTH_SLACK = 2

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def fold(text: str) -> str:
    """Casefold, strip diacritics, punctuation to space, collapse whitespace.

    Punctuation becomes a space rather than nothing, so the two sides stay
    consistent when only one of them has it: a model writing `thanh-toán`
    against a page reading `thanh toán` folds to `thanh toan` either way, where
    deleting the hyphen would give `thanhtoan` against `thanh toan` and match
    nothing. `purchase_listing._key` deletes instead, correctly -- it compares
    single tokens against a fixed marker, so it has no two-sided problem.
    """
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", norm(text))).strip()


def reading_order(words: list[dict]) -> list[dict]:
    """One page's words in reading order: lines top-down, each left-to-right."""
    return [word for line in group_lines(words) for word in line]


def _index(tokens: list[dict]) -> tuple[str, list[tuple[int, int]], list[int]]:
    """Folded text of `tokens`, each kept token's span in it, and its index.

    A token whose fold is empty -- a table rule read as a lone dash, a stray
    quote mark -- is dropped rather than joined in, so it cannot introduce the
    double space that would stop an otherwise exact match. The third value maps
    a position in `spans` back to its index in `tokens`, which is what
    `union_bbox` needs.
    """
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    kept: list[int] = []
    position = 0
    for index, token in enumerate(tokens):
        folded = fold(token.get("text", ""))
        if not folded:
            continue
        if parts:
            position += 1  # the joining space
        parts.append(folded)
        spans.append((position, position + len(folded)))
        kept.append(index)
        position += len(folded)
    return " ".join(parts), spans, kept


def _covering(spans: list[tuple[int, int]], start: int, end: int) -> list[int]:
    return [i for i, (s, e) in enumerate(spans) if e > start and s < end]


def _best_window(
    text: str, spans: list[tuple[int, int]], quote: str,
) -> tuple[int, int, float] | None:
    """`(first, last, ratio)` token positions of the closest window, or None.

    Windows are measured in tokens rather than characters so a hit maps
    straight back to boxes.
    """
    wanted = len(quote.split())
    if not wanted or not spans:
        return None
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(quote)
    best: tuple[int, int, float] | None = None
    for width in range(max(1, wanted - WIDTH_SLACK), wanted + WIDTH_SLACK + 1):
        if width > len(spans):
            break
        for start in range(len(spans) - width + 1):
            candidate = text[spans[start][0]:spans[start + width - 1][1]]
            matcher.set_seq1(candidate)
            # real_quick_ratio and quick_ratio are cheap upper bounds on ratio;
            # skipping on them is what keeps a whole-document sweep affordable.
            if matcher.real_quick_ratio() < MIN_RATIO:
                continue
            if matcher.quick_ratio() < MIN_RATIO:
                continue
            ratio = matcher.ratio()
            if ratio >= MIN_RATIO and (best is None or ratio > best[2]):
                best = (start, start + width - 1, ratio)
    return best


def locate_quote(
    quote: str,
    pages: dict[int, list[dict]],
    page: int | None = None,
) -> dict | None:
    """`{"page", "bbox", "exact", "ratio"}` for `quote`, or None.

    `pages` is one document's entry from `words_by_doc`, i.e. page index within
    the document -> its words -- the same shape `signature_anchors.find_anchors`
    takes, and for the same reason: a word is `{text, x, y, w, h, conf}` and has
    never carried a page, so reading one off a word yields 0 for every quote.

    `page` is the page the reader claimed. It is tried first and is otherwise
    only a hint: at eight words or more a whole-document search lands on the
    wrong occurrence 0% of the time, so honouring the claim strictly would turn
    a model's page slip into an unlocatable quote for no accuracy gain.

    Exact matching is tried on every page before any fuzzy matching on any
    page -- a verbatim hit elsewhere beats a 0.91 near-miss on the claimed one.
    """
    folded = fold(quote)
    if len(folded.split()) < MIN_WORDS:
        return None

    order = ([page] if page in pages else []) \
        + [n for n in sorted(pages) if n != page]
    indexed = []
    for number in order:
        tokens = reading_order(pages[number])
        text, spans, kept = _index(tokens)
        indexed.append((number, tokens, text, spans, kept))

    for number, tokens, text, spans, kept in indexed:
        at = text.find(folded)
        if at < 0:
            continue
        hit = _covering(spans, at, at + len(folded))
        if hit:
            box = union_bbox([tokens[kept[i]] for i in hit])
            return {"page": number, "bbox": box, "exact": True, "ratio": 1.0}

    best: tuple[int, dict, float] | None = None
    for number, tokens, text, spans, kept in indexed:
        window = _best_window(text, spans, folded)
        if window is None:
            continue
        first, last, ratio = window
        if best is None or ratio > best[2]:
            box = union_bbox([tokens[kept[i]] for i in range(first, last + 1)])
            best = (number, box, ratio)
    if best is None:
        return None
    return {"page": best[0], "bbox": best[1], "exact": False, "ratio": best[2]}
