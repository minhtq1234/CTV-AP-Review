"""Extract key fields (with bboxes) from an OCR'd PDF packet into a CtvFolder manifest.

Pure geometry/text logic (scale, line grouping, bbox union, diacritic-insensitive
normalization, anchored pattern search, field assembly) is unit-tested on
synthetic OCR word lists — no PDF/Tesseract needed. The I/O layer (PyMuPDF
render + pytesseract) is verified by running on real packets (see
docs/superpowers/specs/2026-07-13-upload-split-ocr-validate-design.md).

Output shape matches src/ctv/types.ts exactly (CtvFolder/EvidenceDoc/DocPage/
CtvField/CtvSource) so manifests load straight into the existing reviewer.

Identifiers in this file -- CCCDs, tax codes, bank accounts and person
names, in fixtures and in the comments recording what was measured -- are
synthetic stand-ins. The observations are real; the values are not, because
this branch is published to a public remote. Substituted stand-ins preserve
the shape the observation depended on: digit count, a one-digit misread, an
accent-only difference, a truncation.
"""
from __future__ import annotations

import os
import re
import unicodedata

import fitz          # PyMuPDF
import pytesseract
from PIL import Image


# ---------------------------------------------------------------------------
# Pure geometry / text helpers (Task A1)
# ---------------------------------------------------------------------------

def scale_words(words: list[dict], factor: float) -> list[dict]:
    """Scale OCR-pixel word boxes by `factor` (e.g. display_dpi/ocr_dpi).

    Keeps `text`/`conf` untouched; x/y/w/h are multiplied and rounded to int.
    """
    out = []
    for w in words:
        out.append({
            "text": w["text"],
            "x": round(w["x"] * factor),
            "y": round(w["y"] * factor),
            "w": round(w["w"] * factor),
            "h": round(w["h"] * factor),
            "conf": w["conf"],
        })
    return out


def group_lines(words: list[dict], y_tol: int = 8) -> list[list[dict]]:
    """Cluster words into reading lines by y-position; each line x-sorted.

    Words are sorted by y first, then greedily assigned to the current line
    while their y stays within `y_tol` of the line's baseline (the y of the
    first word placed in it); once a word's y exceeds that, a new line starts.
    """
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w["y"])
    lines: list[list[dict]] = []
    current: list[dict] = []
    baseline = None
    for w in ordered:
        if current and abs(w["y"] - baseline) > y_tol:
            lines.append(sorted(current, key=lambda x: x["x"]))
            current = []
            baseline = None
        if not current:
            baseline = w["y"]
        current.append(w)
    if current:
        lines.append(sorted(current, key=lambda x: x["x"]))
    return lines


def union_bbox(words: list[dict]) -> dict:
    """Enclosing bbox {x,y,width,height} of a set of word boxes."""
    xs0 = [w["x"] for w in words]
    ys0 = [w["y"] for w in words]
    xs1 = [w["x"] + w["w"] for w in words]
    ys1 = [w["y"] + w["h"] for w in words]
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


_DIACRITIC_SPECIAL = {"đ": "d", "Đ": "D"}


def norm(s: str) -> str:
    """Casefold + strip Vietnamese diacritics, for accent-insensitive matching."""
    s = "".join(_DIACRITIC_SPECIAL.get(ch, ch) for ch in s)
    decomposed = unicodedata.normalize("NFD", s)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


# ---------------------------------------------------------------------------
# Anchored pattern search (Task A2)
# ---------------------------------------------------------------------------

#: How many lines below an anchor `locate_field` will look for the value.
#: 1 keeps a value tied to its own label's line; only widen per-spec, and only
#: with a measurement (see `locate_field` and the `phi` spec).
_DEFAULT_LOOKAHEAD = 1


PATTERNS = {
    "MST": r"\d{10,13}",
    "CCCD_SPACED": r"\d(?:\s*\d){8,12}",
    "MONEY": r"\d{1,3}(?:[.,]\d{3})+",
    "DATE": r"\d{1,2}/\d{1,2}/\d{4}",
    "ACCOUNT": r"\d{6,16}",
}


def _line_text_and_spans(line: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """Joined (space-separated) line text, plus each word's [start,end) span in it."""
    parts = []
    spans = []
    pos = 0
    for i, w in enumerate(line):
        t = w["text"]
        start = pos
        end = pos + len(t)
        spans.append((start, end))
        pos = end
        if i < len(line) - 1:
            pos += 1  # the joining space
    text = " ".join(w["text"] for w in line)
    return text, spans


def _search_line(line: list[dict], pattern: str) -> dict | None:
    """Search `pattern` over `line`'s joined text; map the match back to words."""
    text, spans = _line_text_and_spans(line)
    m = re.search(pattern, text)
    if not m:
        return None
    s, e = m.start(), m.end()
    matched_words = [w for w, (ws, we) in zip(line, spans) if we > s and ws < e]
    if not matched_words:
        return None
    value = re.sub(r"\s+", "", m.group(0))
    confidence = min(w["conf"] for w in matched_words) / 100
    return {"value": value, "bbox": union_bbox(matched_words), "confidence": confidence}


def find_in_lines(
    lines: list[list[dict]],
    anchors: list[str],
    pattern: str,
    allow_next_line: bool = True,
) -> list[dict]:
    """For each line whose text (accent-insensitively) contains an anchor,
    search that line (and optionally the next) for `pattern`; return one hit
    per matching anchor line: `{value, bbox, confidence}`.
    """
    anchors_norm = [norm(a) for a in anchors]
    hits = []
    for idx, line in enumerate(lines):
        text = " ".join(w["text"] for w in line)
        if not any(a in norm(text) for a in anchors_norm):
            continue
        hit = _search_line(line, pattern)
        if hit is None and allow_next_line and idx + 1 < len(lines):
            hit = _search_line(lines[idx + 1], pattern)
        if hit is not None:
            hits.append(hit)
    return hits


def _norm_line_text_and_spans(line: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """Like `_line_text_and_spans`, but built from each word's NORMALIZED
    (accent/case-insensitive) text -- lets an anchor's match span in the
    normalized text be mapped back to the words it covers (see
    `_anchor_word_span`). `norm` is a per-character transform (casefold +
    strip combining marks) that leaves the joining space untouched, so this
    is equivalent to `norm(" ".join(w["text"] for w in line))`.
    """
    parts = []
    spans = []
    pos = 0
    for i, w in enumerate(line):
        t = norm(w["text"])
        start = pos
        end = pos + len(t)
        spans.append((start, end))
        pos = end
        if i < len(line) - 1:
            pos += 1  # the joining space
    text = " ".join(norm(w["text"]) for w in line)
    return text, spans


def _anchor_word_span(line: list[dict], anchor_norm: str) -> list[int] | None:
    """Word indices in `line` covered by `anchor_norm`'s first match in the
    line's normalized text, or None if it doesn't occur on this line."""
    text, spans = _norm_line_text_and_spans(line)
    idx = text.find(anchor_norm)
    if idx < 0:
        return None
    s, e = idx, idx + len(anchor_norm)
    covered = [i for i, (ws, we) in enumerate(spans) if we > s and ws < e]
    return covered or None


# #005: the OCR confidence (0-100) at/above which a word is treated as printed
# LABEL text rather than a handwritten/illegible value. A value lands in the
# "unread" branch in the first place because it *didn't* OCR into a matching
# pattern -- handwriting that couldn't be read reliably scores LOW confidence,
# so this doubles as the signal that keeps the "next label" search (below)
# from being fooled by an illegible value that happens to contain no digits
# (e.g. garbled strokes OCR'd as letters) into treating it as a label word.
_MIN_LABEL_CONF = 50

# Small horizontal pad (px) added after a label's own right edge, so the
# located region starts just clear of the label's text rather than touching it.
_LABEL_RIGHT_PAD = 4

_all_anchor_tokens_cache: list[list[str]] | None = None


def _all_anchor_tokens() -> list[list[str]]:
    """Every FIELD_SPECS anchor, tokenized + normalized, deduped -- the
    global "known label" vocabulary `_next_label_start` checks against so it
    recognizes ANY field's label (not just the one currently being located)
    as a boundary. Lazily built (FIELD_SPECS is defined further down this
    module) and cached; safe since it only depends on the fixed spec table.
    """
    global _all_anchor_tokens_cache
    if _all_anchor_tokens_cache is None:
        seen: set[tuple[str, ...]] = set()
        toks: list[list[str]] = []
        for spec in FIELD_SPECS:
            for a in spec["anchors"]:
                t = tuple(norm(a).split())
                if t and t not in seen:
                    seen.add(t)
                    toks.append(list(t))
        _all_anchor_tokens_cache = toks
    return _all_anchor_tokens_cache


def _looks_like_label_word(w: dict) -> bool:
    """A word plausibly belonging to a printed LABEL, not a value: no digits
    (Vietnamese label words never are) and OCR'd with reasonable confidence
    (see `_MIN_LABEL_CONF`)."""
    core = w["text"].rstrip(":;., ").strip()
    return bool(core) and not any(ch.isdigit() for ch in core) and w["conf"] >= _MIN_LABEL_CONF


def _matches_anchor_at(line: list[dict], idx: int, anchor_tokens: list[list[str]]) -> bool:
    """True if a KNOWN field anchor's tokens match starting at `line[idx]`."""
    words_norm = [norm(w["text"]) for w in line[idx:idx + 4]]
    return any(tokens and words_norm[:len(tokens)] == tokens for tokens in anchor_tokens)


def _next_label_start(line: list[dict], from_idx: int, max_label_words: int = 4) -> int | None:
    """Index of the next label on this line at/after `from_idx` -- either a
    run of words matching a KNOWN field anchor, or a short label-shaped run
    (see `_looks_like_label_word`) whose last word ends with ':' (catches
    labels the tool doesn't track as a field, e.g. "Ngày cấp:", "Nơi cấp:")
    -- so a located-but-unread region never runs past where the NEXT field's
    label begins on a multi-field line (#005), or `None` if there isn't one.
    """
    anchor_tokens = _all_anchor_tokens()
    for i in range(from_idx, len(line)):
        if _matches_anchor_at(line, i, anchor_tokens):
            return i
        for j in range(i, min(i + max_label_words, len(line))):
            if not _looks_like_label_word(line[j]):
                break  # hit a value-shaped (digit/low-confidence) word -- no label run here
            if line[j]["text"].rstrip().endswith(":"):
                return i
    return None


def _geometric_value_slot(
    line: list[dict], label_words: list[dict], label_end_idx: int, page_lines: list[list[dict]],
) -> dict:
    """The VALUE SLOT for a labeled-but-unreadable occurrence, computed
    GEOMETRICALLY from the label's own bbox -- NOT from "the next word token
    after the label". Shared by `_label_region_bbox` (#005, pattern fields)
    and `find_name`'s located fallback (#008).

    #005: a handwritten value that OCR'd to zero usable word tokens
    (illegible enough that Tesseract found nothing there at all -- the
    common case for a scrawled CCCD) makes "the next token after the label"
    literally BE the next field's own label ("Ngày cấp"), so any
    token-index-based skip logic lands the region's START on the wrong
    field. Anchoring x0 to the label's own right edge sidesteps this
    entirely: it's correct whether the gap has zero, one, or many tokens.

    - x0 = the right edge of `label_words` (the label's own matched words),
      + a tiny pad (`_LABEL_RIGHT_PAD`).
    - x1 = the left edge of the next label on the same line, searched from
      `label_end_idx` (see `_next_label_start`), if any; else x0 + a
      default width (~30% of the page, estimated from `page_lines`).
    - y = the label LINE's own y-span (not just the matched words'), so
      cross-word y jitter doesn't affect the highlight's height.
    """
    x0 = max(w["x"] + w["w"] for w in label_words) + _LABEL_RIGHT_PAD
    y0 = min(w["y"] for w in line)
    y1 = max(w["y"] + w["h"] for w in line)
    next_idx = _next_label_start(line, label_end_idx)
    width = (line[next_idx]["x"] - x0) if next_idx is not None else None
    if width is None or width <= 0:
        # No next label on this line (or it's degenerately close) -- a
        # bounded default slot, not "to the end of the line" (that's
        # exactly what used to latch onto unrelated trailing text).
        page_width = max((w["x"] + w["w"] for pl in page_lines for w in pl), default=0)
        width = max(round(page_width * 0.3), 40)
    return {"x": x0, "y": y0, "width": width, "height": y1 - y0}


def _label_region_bbox(line: list[dict], anchors_norm: list[str], page_lines: list[list[dict]]) -> dict:
    """Where to point the loupe when a line's label is present but its value
    isn't readable: `_geometric_value_slot` anchored on whichever of
    `anchors_norm` matches this line (see `_anchor_word_span`).
    """
    for a in anchors_norm:
        covered = _anchor_word_span(line, a)
        if not covered:
            continue
        label_words = [line[i] for i in covered]
        return _geometric_value_slot(line, label_words, max(covered) + 1, page_lines)
    # Anchor matched on the whole joined-text check but no per-word span was
    # found (shouldn't normally happen) -- the whole line is still a better
    # location than nothing.
    return union_bbox(line)


#: How much of the shorter line's height must overlap for two lines to count as
#: the same visual row. `group_lines` baselines a line on its first word's y, so
#: a wide row with a little vertical jitter splits into fragments -- and the
#: fragment holding the value can sort *before* the one holding the label. Page
#: 251 of the July submission split its CCCD row into six, with the number two
#: lines above its own label, and the packet's CCCD went unread.
_ROW_OVERLAP = 0.5


def _span(line: list[dict]) -> tuple[int, int]:
    return (min(w["y"] for w in line),
            max(w["y"] + w["h"] for w in line))


def _same_row(a: tuple[int, int], b: tuple[int, int],
              overlap: float = _ROW_OVERLAP) -> bool:
    shared = min(a[1], b[1]) - max(a[0], b[0])
    shortest = min(a[1] - a[0], b[1] - b[0])
    return shortest > 0 and shared / shortest >= overlap


def _row_words(lines: list[list[dict]], idx: int) -> list[dict]:
    """Every word on the same visual row as `lines[idx]`, in reading order.

    Reassembles a row `group_lines` split, so a label can find the value beside
    it whichever fragment happened to sort first.
    """
    band = _span(lines[idx])
    words = [w for line in lines if _same_row(band, _span(line)) for w in line]
    return sorted(words, key=lambda w: w["x"])


# ---------------------------------------------------------------------------
# Party columns (#011) — which of a two-column signature/contact block's two
# names belongs to the CTV.
#
# Contracts and biên bản end (and open, in the "Thông tin liên hệ của các
# Bên" block) in TWO COLUMNS, one per party, and BOTH carry the same generic
# "Họ và tên:" label: VNG's own signatory on the left, the CTV -- the person
# the roster names -- on the right. `find_name` used to reduce a page to one
# name by CONFIDENCE, and confidence is legibility, not correctness: measured
# on the July batch, VNG's signatory reads just as crisply as the CTV's name
# (abs page 82: 'Ngô Gia Bảo Long' 0.96 vs 'Bùi Quang Vinh' 0.96; abs page
# 247: 'Vương Đức Khoa' 0.94 vs 'Hồ Tắn Nghĩa' 0.85), so the wrong party won
# and a correctly-matched packet was reported as a name mismatch -- a `no`,
# which drives "cần gửi lại" on valid paperwork.
#
# The party evidence is printed on the page itself: the block's own column
# HEADER. It is never a correctness proxy -- it says nothing about whether a
# read is right, only about WHICH PARTY the words under it describe -- so it
# decides the party and confidence survives only as the tiebreak between two
# reads of the SAME party's name.
#
# Detection is GEOMETRIC, not phrase-based, because the left (VNG) header does
# not survive OCR: on all three failing pages "BÊN SỬ DỤNG DỊCH VỤ" reads as
# the bare logo word 'VNG' (abs 82 x=232..278, abs 247 x=236..284, abs 275
# x=236..286). Requiring both headers would have been a no-op on every one of
# them. So a row qualifies on the ONE header that does survive plus a
# word-free band: content ending to its left, a gutter-wide gap, and the CTV
# header run alone to the right of that gap.
# ---------------------------------------------------------------------------

#: The CTV's ("party B") column header. Its x-position is what orients the
#: whole mechanism: the detection below requires content to its LEFT, so the
#: side of the gutter that is the CTV's is read off the page, never assumed.
_PARTY_B_HEADER = "ben cung ung dich vu"

#: Name anchors BOTH columns carry, so an occurrence of one says nothing by
#: itself about which party it names. Ambiguity is a property of the PHRASE,
#: not of the field spec, which is why it lives here rather than in
#: FIELD_SPECS. Every other `hoten` anchor ("bên cung ứng dịch vụ", "tên
#: người nộp thuế", "tên tôi là") is party-specific by construction.
_AMBIGUOUS_NAME_ANCHORS = {"ho va ten"}

#: Minimum gutter width, as a fraction of the page's own measured width --
#: NOT a pixel constant, so it holds at any render dpi (the ingest renders at
#: display_dpi=150, but nothing here depends on that). Measured gutters on the
#: three failing pages are 158-198px on a 1241px-wide page, i.e. 13-16%; the
#: floor sits well under that and still well over ordinary intra-column
#: label-value gaps (the widest measured, "CCCD số  :  001100000051", is
#: ~120px ≈ 10%, and it is never a candidate anyway -- see `_party_of`: the
#: gutter CLASSIFIES words, it never cuts a line).
_MIN_GUTTER_FRAC = 0.045

#: Rows below the header that must keep the same band clear for the block to
#: count as two columns. Two, measured: on all three failing pages the header
#: is followed by the name row AND the email row, both column-split. One row
#: would let a single OCR-thinned prose line masquerade as a column header.
_MIN_COLUMN_ROWS = 2


def _visual_rows(lines: list[list[dict]]) -> list[list[dict]]:
    """The page's distinct VISUAL rows, top to bottom -- `_row_words` applied
    to every line, deduped, so a row `group_lines` split into fragments (the
    common case for these blocks: abs page 275's header is 'VNG' in one
    fragment and 'Bên Cung Ứng Dịch Vụ' in another) is considered once, whole.
    """
    rows: list[list[dict]] = []
    seen: set[frozenset[int]] = set()
    for idx in range(len(lines)):
        row = _row_words(lines, idx)
        # `_same_row` needs a positive height, so a line whose boxes all OCR'd
        # with h=0 (real July-batch pages carry a few) matches no row at all,
        # its own included. It isn't a visual row; skip it.
        if not row:
            continue
        key = frozenset(id(w) for w in row)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return sorted(rows, key=lambda r: _span(r)[0])


def _word_free_gaps(row: list[dict], page_width: int) -> list[tuple[int, int]]:
    """`row`'s word-free x-bands, left to right, including the margins either
    side of its content -- a row whose only mark sits between the columns (abs
    page 82's header is followed by a stray '¬' at x=624..649) still leaves the
    gutter clear on one side of that mark, and the margin bands are how that is
    expressed. Uses the running right edge so an overlapping or out-of-order
    box can't invent a negative gap.
    """
    ordered = sorted(row, key=lambda w: w["x"])
    if not ordered:
        return [(0, page_width)]
    gaps = [(0, ordered[0]["x"])]
    right = None
    for w in ordered:
        if right is not None and w["x"] > right:
            gaps.append((right, w["x"]))
        right = max(right or 0, w["x"] + w["w"])
    gaps.append((right, max(page_width, right)))
    return gaps


def _is_two_sided(row: list[dict], band: tuple[int, int]) -> bool:
    """True if `row` has a word entirely left of `band` AND one entirely right
    of it -- i.e. this row really is split across the two columns, not a
    full-width or single-column row that merely happens to leave the gutter
    clear. What keeps a block from creeping down the page over unrelated
    single-column text (which would then get classified, and dropped, as
    VNG's).
    """
    left = any(w["x"] + w["w"] <= band[0] for w in row)
    right = any(w["x"] >= band[1] for w in row)
    return left and right


def _party_header_band(row: list[dict], min_gutter: int) -> tuple[int, int] | None:
    """The word-free band separating a two-column block's two headers on
    `row`, or None if this row isn't such a header.

    Three conditions, all measured on abs page 275 (packet 35's biên bản):
    - low-confidence specks are dropped first (`_MIN_LABEL_CONF`): that page's
      header row also carries '+}' at conf 43 (x=646..670, right beside the
      header) and a stray '|' at conf 26 (x=1087..1103, past its end). Without
      the filter the first defeats the gap test and the second defeats the
      end-of-row test below; with it, the row qualifies.
    - the CTV header run must END the row, with content to its LEFT: that is
      what makes the row a two-column HEADER rather than a prose sentence
      mentioning the party, and it is also what tells us the CTV's column is
      the right-hand one (read off the page, never assumed).
    - the gap immediately left of the run must be at least `min_gutter` wide.
    """
    words = [w for w in sorted(row, key=lambda w: w["x"]) if w["conf"] >= _MIN_LABEL_CONF]
    covered = _anchor_word_span(words, _PARTY_B_HEADER)
    if not covered:
        return None
    first, last = min(covered), max(covered)
    if first == 0 or last != len(words) - 1:
        return None
    left_edge = max(w["x"] + w["w"] for w in words[:first])
    right_edge = words[first]["x"]
    if right_edge - left_edge < min_gutter:
        return None
    return (left_edge, right_edge)


def _intersect_gap(
    band: tuple[int, int], row: list[dict], min_gutter: int, page_width: int,
) -> tuple[int, int] | None:
    """`band` narrowed by whichever of `row`'s word-free gaps overlaps it
    most, or None if no gap leaves at least `min_gutter`.

    "Widest overlap" is what keeps a small intra-column label-value gap from
    being mistaken for the gutter: abs page 82's name row has a 10px gap after
    'tên:' and a 165px one between the columns, both inside the header's band.
    """
    best = None
    for g0, g1 in _word_free_gaps(row, page_width):
        lo, hi = max(band[0], g0), min(band[1], g1)
        if hi - lo >= min_gutter and (best is None or hi - lo > best[1] - best[0]):
            best = (lo, hi)
    return best


def _party_column_blocks(lines: list[list[dict]]) -> list[dict]:
    """The page's two-column party blocks: `[{y0, y1, gutter}, ...]`.

    A block opens on a row `_party_header_band` accepts and extends downward
    while the following rows keep a gutter-wide slice of the SAME band clear
    (`_intersect_gap`) -- so the divide is confirmed by every row it is applied
    to, and the gutter is the midpoint of the band that survived ALL of them,
    which is why it cannot land inside a column that any block row fills. Only
    rows that really are split across both columns (`_is_two_sided`) extend the
    block's y-range; the walk stops at a row that blocks the band, or at the
    second consecutive row that is not two-sided -- one stray row does not
    close a block (abs page 82's header is followed by a lone '¬' speck before
    the name row), two mean the block has ended.

    A block needs `_MIN_COLUMN_ROWS` two-sided rows to count at all; a page
    with no qualifying header yields no blocks and leaves `find_name` at its
    previous behaviour -- a deliberate no-fix (no party evidence, nothing to
    decide with), not a regression.
    """
    page_width = max((w["x"] + w["w"] for line in lines for w in line), default=0)
    min_gutter = max(round(page_width * _MIN_GUTTER_FRAC), 1)
    rows = _visual_rows(lines)
    blocks = []
    for i, row in enumerate(rows):
        band = _party_header_band(row, min_gutter)
        if band is None:
            continue
        y1 = _span(row)[1]
        n_rows = 0
        skipped = 0
        for below in rows[i + 1:]:
            narrowed = _intersect_gap(band, below, min_gutter, page_width)
            if narrowed is None:
                break
            if not _is_two_sided(below, narrowed):
                skipped += 1
                if skipped >= 2:
                    break
                continue
            skipped = 0
            band = narrowed
            y1 = _span(below)[1]
            n_rows += 1
        if n_rows >= _MIN_COLUMN_ROWS:
            blocks.append({"y0": _span(row)[0], "y1": y1, "gutter": (band[0] + band[1]) // 2})
    return blocks


def _party_of(bbox: dict, blocks: list[dict]) -> str | None:
    """Which party's column `bbox` sits in: "b" (the CTV's), "a" (VNG's),
    "straddle" (it crosses the divide, so its words belong to neither party
    alone), or None when no block covers it -- no party evidence here.

    The gutter only ever CLASSIFIES a bbox; nothing in this module cuts a line
    or a value at it. That is what keeps a mis-placed gutter from truncating a
    correct read into a wrong-token-count value (`compare_values`
    `_person_verdict` treats a differing token count as an outright mismatch,
    so a truncated name would be a NEW false `no`); the worst it can do is
    call a read "straddle", which lands it in "cần xem".
    """
    cy = bbox["y"] + bbox["height"] / 2
    for b in blocks:
        if not (b["y0"] <= cy <= b["y1"]):
            continue
        x0, x1 = bbox["x"], bbox["x"] + bbox["width"]
        if x1 <= b["gutter"]:
            return "a"
        if x0 >= b["gutter"]:
            return "b"
        return "straddle"
    return None


def locate_field(lines: list[list[dict]], spec: dict) -> list[dict]:
    """For each line whose text contains one of `spec["anchors"]` (accent-
    insensitively), produce exactly one hit -- never zero for a matching
    line, never more than one -- so a field's LOCATION is found even when
    its value can't be read (e.g. handwritten):

    - if any of `spec["patterns"]` matches this line (or, failing that, the
      next `spec["lookahead"]` lines -- 1 by default, the same lookahead as
      `find_in_lines`) -> a readable hit: `{value, bbox, confidence}` from the
      matched words;
    - else -> a located-but-unread hit: `value=""`, `bbox` = the value slot
      on this line (see `_label_region_bbox`), `confidence=0.0`.

    This is the "locate & look" fix for docs/test-findings.md #004: a label
    reliably found is worth a navigable "cần xem" chip even when its
    handwritten value isn't -- the OCR'd value is a hint, never the gate.

    The lookahead is per-spec rather than global on purpose. Widening it helps
    only where the anchor lands on a heading rather than the value's own line
    (see `phi`), and it is actively unsafe for a broad pattern: ACCOUNT is
    `\\d{6,16}`, so three lines of slack would let `tk` capture a CCCD or MST
    from a neighbouring row -- the read count would stay high while the values
    silently became wrong. Widen a field only with a measurement for it.
    """
    anchors_norm = [norm(a) for a in spec["anchors"]]
    patterns = spec.get("patterns", [])
    lookahead = int(spec.get("lookahead", _DEFAULT_LOOKAHEAD))
    hits = []
    for idx, line in enumerate(lines):
        text = " ".join(w["text"] for w in line)
        if not any(a in norm(text) for a in anchors_norm):
            continue
        hit = None
        row = None
        for pattern in patterns:
            hit = _search_line(line, pattern)
            if hit is None:
                # the label's own row, reassembled -- the value may have sorted
                # into a different line despite sitting beside the label
                row = row if row is not None else _row_words(lines, idx)
                hit = _search_line(row, pattern)
            if hit is None:
                # Nearest line wins, so a wider window never pulls a further
                # value in ahead of a closer one.
                for ahead in range(idx + 1, min(idx + 1 + lookahead, len(lines))):
                    hit = _search_line(lines[ahead], pattern)
                    if hit is not None:
                        break
            if hit is not None:
                break
        if hit is None:
            hit = {"value": "", "bbox": _label_region_bbox(line, anchors_norm, lines), "confidence": 0.0}
        hits.append(hit)
    return hits


def _clean_tok(s: str) -> str:
    return s.strip(" :;.,")


def _is_labeled_anchor(line: list[dict], i: int, n: int) -> bool:
    """True if the anchor at `line[i:i+n]` sits in a labeled/signature
    context, not flowing prose: immediately followed by a ':' (attached to
    the last anchor word, or as its own token right after), or written in
    ALL CAPS. Real contracts render the signature-block party label in caps
    ("BÊN CUNG ỨNG DỊCH VỤ") while ordinary prose repeats the same phrase in
    mixed case ("Bên Cung Ứng Dịch Vụ ...") dozens of times — that repetition
    is exactly the false-positive source this guards against.
    """
    last_word = line[i + n - 1]["text"]
    if last_word.rstrip().endswith(":"):
        return True
    if i + n < len(line) and line[i + n]["text"].strip().startswith(":"):
        return True
    anchor_text = " ".join(w["text"] for w in line[i:i + n])
    letters = [ch for ch in anchor_text if ch.isalpha()]
    return bool(letters) and anchor_text == anchor_text.upper()


def _looks_like_person_name(words: list[dict]) -> bool:
    """2-5 alphabetic tokens, each starting with an uppercase letter
    (Vietnamese uppercase incl. Đ/Ứ/Ô/... included) -- rejects stray digits/
    punctuation and rejects continuing into lowercase sentence prose (e.g.
    "sẽ", "các", "đồng ý rằng"), which is exactly what follows a mid-sentence
    anchor occurrence.
    """
    if not (2 <= len(words) <= 5):
        return False
    for w in words:
        core = w["text"].strip(" :;.,")
        if not core or not core.isalpha() or not core[0].isupper():
            return False
    return True


#: Name-hit ranks -- two levels, not a score. Whether the words are the CTV's
#: at all decides; confidence is only ever the tiebreak BETWEEN TWO READS OF
#: THE SAME PARTY'S NAME, never a proxy for which party is right.
#: - 1, party-certain: either the page's own column header places the name in
#:      the CTV's column (`_party_of` == "b"), or the anchor phrase that found
#:      it is party-specific ("bên cung ứng dịch vụ", "tên tôi là", ...).
#: - 0, unplaced: a readable name from the ambiguous "Họ và tên" with no column
#:      evidence at all, and every located-but-unread hit.
#:
#: The two kinds of party evidence are deliberately EQUAL. Ranking the column
#: above the phrase was measured on the July batch and made things worse: on
#: packets 22 and 28 the two-column block on contract page 1 reads the same
#: name a diacritic worse than the party-labeled signature block on page 0
#: (0.55 vs 0.96, 0.91 vs 0.93), so promoting it turned two matches into
#: "cần xem" -- and it bought nothing, because the truncation that motivated
#: the promotion is fixed at its source by the row reassembly in
#: `_row_value_extension`.
_RANK_PARTY_CERTAIN = 1
_RANK_UNPLACED = 0


def _hit_rank(hit: dict) -> tuple[int, float]:
    """Sort/selection key for one hit: `(rank, confidence)`. Hits from
    `locate_field` carry no "rank", so for them this degenerates to the
    confidence-only key it replaced.
    """
    return (hit.get("rank", _RANK_UNPLACED), hit["confidence"])


def _dedupe_and_cap(hits: list[dict], max_n: int = 3) -> list[dict]:
    """Collapse identical values to their highest-confidence hit; keep at
    most `max_n`, highest-confidence first -- so a handful of genuine
    labeled occurrences don't get diluted by noise, and duplicates don't
    inflate the source count.

    Ordered by `_hit_rank` (party evidence first, confidence as the
    tiebreak -- see `find_name`), DESCENDING, so a rank-0 hit can't consume a
    cap slot ahead of a party-confirmed one. With no ranks in play the key
    degenerates to the previous `-confidence` ordering, and `sorted(...,
    reverse=True)` is stable, so equal-confidence hits keep their page order
    exactly as before.
    """
    best_by_value: dict[str, dict] = {}
    for h in hits:
        prev = best_by_value.get(h["value"])
        if prev is None or _hit_rank(h) > _hit_rank(prev):
            best_by_value[h["value"]] = h
    ordered = sorted(best_by_value.values(), key=_hit_rank, reverse=True)
    return ordered[:max_n]


def _primary_anchor_match(line: list[dict], tokenized: list[list[str]]) -> tuple[int, int, int] | None:
    """The occurrence `find_name` has always used on a line: the FIRST anchor
    in `anchors` order (which is party-specific-first) at its first matching
    position on this line. Unchanged, deliberately -- #011 adds an extension
    and a party classification on top of this occurrence, never a different
    choice of it.
    """
    words_norm = [_clean_tok(norm(w["text"])) for w in line]
    for a_idx, tokens in enumerate(tokenized):
        n = len(tokens)
        for i in range(len(words_norm) - n + 1):
            if words_norm[i:i + n] == tokens:
                return (i, n, a_idx)
    return None


def _anchor_occurrences(words: list[dict], tokenized: list[list[str]]) -> list[tuple[int, int, int]]:
    """Every `(start, n_words, anchor_index)` anchor occurrence in `words`,
    left to right, non-overlapping; at each position the first anchor in
    `anchors` order wins. Used on a REASSEMBLED ROW, where a two-column
    signature block puts both parties' labels side by side.
    """
    words_norm = [_clean_tok(norm(w["text"])) for w in words]
    out = []
    i = 0
    while i < len(words_norm):
        for a_idx, tokens in enumerate(tokenized):
            n = len(tokens)
            if tokens and words_norm[i:i + n] == tokens:
                out.append((i, n, a_idx))
                i += n - 1
                break
        i += 1
    return out


def _strip_leading_colon(value_words: list[dict]) -> list[dict]:
    """Drop a ':' that OCR'd as its own word between label and value (abs
    page 85 has one at x=512, from a different `group_lines` fragment than
    either side)."""
    if value_words and value_words[0]["text"].strip() == ":":
        return value_words[1:]
    return value_words


def _bounded_value_words(words: list[dict], start: int, occurrences: list[tuple[int, int, int]]) -> list[dict]:
    """`words[start:]`, cut where the NEXT name anchor begins.

    Bounded on a KNOWN NAME ANCHOR, never on `_next_label_start`: measured on
    abs page 275's reassembled row ('Họ và tên: Trần Văn Tiến Họ và tên: Hoàng
    Nguyễn Hải Đăng'), `_next_label_start(row, 3)` returns 5, not 6 -- its
    short-colon-terminated-run rule fires on ['Tiến','Họ','và','tên:'] before
    it ever reaches the anchor, so a 3-token value would lose its last token.
    29 of the July batch's 41 roster names are 3 tokens, and
    `compare_values._person_verdict` makes a differing token count an outright
    MISMATCH -- that truncation would be a new false `no`, not a near miss.
    """
    end = next((i for i, _n, _a in occurrences if i >= start), len(words))
    return _strip_leading_colon(words[start:end])


def _swallows_a_label(added: list[dict], tokenized: list[list[str]]) -> bool:
    """True if `added` runs into a neighbouring label: its tail matches the
    start of a known name anchor ('Họ' alone is enough -- it opens "họ và
    tên")."""
    words_norm = [_clean_tok(norm(w["text"])) for w in added]
    for k in range(len(words_norm)):
        tail = words_norm[k:]
        if any(tokens[:len(tail)] == tail for tokens in tokenized):
            return True
    return False


def _legible_row_value(words: list[dict]) -> bool:
    """True if every word of a ROW-derived value OCR'd as real text
    (`_MIN_LABEL_CONF`).

    Only row-derived values are held to this: a value reassembled from a whole
    visual row can pick up a mark from ANYWHERE on that row, and on abs page
    170 (packet 20's contract) it did -- two scanner-edge specks, 'ZZ' at conf
    2 and 'NI' at conf 1, sitting at x=1222..1240 in the page margin. Both are
    capitalised and alphabetic, so `_looks_like_person_name` accepts them, and
    'Tạ Văn Cường' became the 5-token 'Tạ Văn Cường ZZ NI' at confidence
    0.01 -- a wrong token count, which `compare_values._person_verdict` makes
    an outright MISMATCH: a NEW false `no`.

    The check rejects the whole row-derived value rather than truncating it at
    the speck. Truncating would be the same false `no` in the other direction
    the moment a real name token happened to OCR below the floor.
    """
    return bool(words) and all(w["conf"] >= _MIN_LABEL_CONF for w in words)


def _row_value_extension(
    line_value: list[dict], row_value: list[dict], tokenized: list[list[str]],
) -> list[dict] | None:
    """`row_value` if it is a strict PREFIX EXTENSION of `line_value` that
    still reads as a person's name -- else None, and the line's own read
    stands untouched.

    Strict prefix means the row's value opens with exactly the words the
    line's value had, in order (identity, not text), and adds at least one
    more. That is the only shape a `group_lines` split of ONE value can take:
    abs page 85 (packet 9's biên bản) put 'Phát' in a different fragment from
    'Bùi Quang', and the truncated 'Bùi Quang' is a hard MISMATCH under
    `compare_values._person_verdict`'s token-count rule -- the packet stayed
    `no` even after the contract page was read correctly.

    The guard matters as much as the extension: `_looks_like_person_name` is
    shape-only, so absorbing ONE stray capitalised token (the neighbouring
    column's 'Họ') would turn a correct 3-token read into a 4-token one, which
    is that same hard MISMATCH in the other direction.
    """
    if not line_value or len(row_value) <= len(line_value):
        return None
    if any(a is not b for a, b in zip(line_value, row_value)):
        return None
    if _swallows_a_label(row_value[len(line_value):], tokenized):
        return None
    if not _legible_row_value(row_value) or not _looks_like_person_name(row_value):
        return None
    return row_value


def _readable_name_hit(
    value_words: list[dict], label_words: list[dict], party_scoped: bool, blocks: list[dict],
) -> dict | None:
    """One readable name occurrence, classified against the page's own party
    columns: a hit at `_RANK_PARTY_CERTAIN` / `_RANK_UNPLACED`, a
    located-but-unread hit, or None (not a source at all).

    - no block covers this occurrence -> no party evidence, so today's
      behaviour stands: the value as read, party-certain only if its anchor
      phrase is party-specific. A deliberate no-fix, not a regression.
    - label AND value both in the CTV's column -> `_RANK_PARTY_CERTAIN`. This
      is the only positive positional signal here, and it is page geometry,
      never a correctness proxy: abs page 247 publishes the 0.85 CTV read over
      the 0.94 VNG one.
    - VNG's column, reached by the ambiguous "Họ và tên" -> None. VNG's
      signatory is not evidence about the CTV; counting it is what produced the
      false `no`.
    - anything else (the value crosses the divide, or the label and value sit
      on opposite sides, or a party-specific anchor's `allow_next_line` guess
      landed in VNG's column) -> located-but-unread at the words actually
      read, so the loupe still points at the real text. `evaluate`
      `_compare_reads` drops an unreadable copy from the worst-wins fold
      instead of counting it as disagreement, so this is "cần xem", never a
      `no`.
    """
    bbox = union_bbox(value_words)
    label_party = _party_of(union_bbox(label_words), blocks)
    value_party = _party_of(bbox, blocks)
    readable = {
        "value": " ".join(w["text"] for w in value_words),
        "bbox": bbox,
        "confidence": min(w["conf"] for w in value_words) / 100,
    }
    if label_party is None and value_party is None:
        readable["rank"] = _RANK_PARTY_CERTAIN if party_scoped else _RANK_UNPLACED
        return readable
    if label_party == "b" and value_party == "b":
        readable["rank"] = _RANK_PARTY_CERTAIN
        return readable
    if label_party == "a" and not party_scoped:
        return None
    return {"value": "", "bbox": bbox, "confidence": 0.0, "rank": _RANK_UNPLACED}


def _extra_column_name_hit(
    row: list[dict], i: int, n: int, a_idx: int, anchors: list[str],
    occurrences: list[tuple[int, int, int]], blocks: list[dict],
    page_lines: list[list[dict]],
) -> dict | None:
    """A labeled name occurrence that only the REASSEMBLED ROW carries -- the
    second column of a two-column signature block, and on abs page 275 the
    only place the CTV's own name exists at all: `group_lines` split its label
    across two fragments ('Họ' at x=670 in one, 'và tên:' in another), so no
    single line holds it.

    Considered only when the page's own column divide places the label in the
    CTV's column. With no party evidence an extra candidate is just another
    confident guess about a name that might as easily be VNG's, and
    `_best_hit` would let it win on confidence -- precisely the failure this
    change is about. When the label IS the CTV's but its value can't be
    trusted, the occurrence is still worth a navigable "cần xem" chip (#008),
    which is what the unread hit at the end is.
    """
    if not _is_labeled_anchor(row, i, n):
        return None
    label_words = row[i:i + n]
    if _party_of(union_bbox(label_words), blocks) != "b":
        return None
    value_words = _bounded_value_words(row, i + n, occurrences)
    if _legible_row_value(value_words) and _looks_like_person_name(value_words):
        return _readable_name_hit(
            value_words, label_words, anchors[a_idx] not in _AMBIGUOUS_NAME_ANCHORS, blocks)
    return {
        "value": "",
        "bbox": _geometric_value_slot(row, label_words, i + n, page_lines),
        "confidence": 0.0,
        "rank": _RANK_UNPLACED,
    }


def _primary_name_hit(
    lines: list[list[dict]], idx: int, row: list[dict], primary: tuple[int, int, int],
    anchors: list[str], tokenized: list[list[str]],
    occurrences: list[tuple[int, int, int]], allow_next_line: bool, blocks: list[dict],
) -> dict | None:
    """The hit for the occurrence `find_name` has always used on this line
    (`_primary_anchor_match`), with #011's two additions layered on it.
    """
    line = lines[idx]
    li, n, a_idx = primary
    if not _is_labeled_anchor(line, li, n):
        return None
    label_words = line[li:li + n]
    party_scoped = anchors[a_idx] not in _AMBIGUOUS_NAME_ANCHORS
    # today's value: the rest of the label's own line, or the whole next line
    value_words = _strip_leading_colon(line[li + n:])
    if not value_words and allow_next_line and idx + 1 < len(lines):
        value_words = lines[idx + 1]
    # the same label's value on its reassembled row, bounded at the next label
    row_i = next((k for k, w in enumerate(row) if w is line[li]), None)
    row_value: list[dict] = []
    if row_i is not None and (row_i, n, a_idx) in occurrences:
        row_value = _bounded_value_words(row, row_i + n, occurrences)
    if (_party_of(union_bbox(label_words), blocks) == "b"
            and _legible_row_value(row_value) and _looks_like_person_name(row_value)):
        # The divide says these words are the CTV's own. Use the BOUNDED row
        # value: when `group_lines` merges both columns into one line, the
        # unbounded value runs straight into VNG's column (abs page 275 read
        # 'Văn Họ' that way).
        value_words = row_value
    else:
        extended = _row_value_extension(value_words, row_value, tokenized)
        if extended is not None:
            value_words = extended
    if value_words and _looks_like_person_name(value_words):
        return _readable_name_hit(value_words, label_words, party_scoped, blocks)
    return {
        "value": "",
        "bbox": _geometric_value_slot(line, label_words, li + n, lines),
        "confidence": 0.0,
        "rank": _RANK_UNPLACED,
    }


def find_name(lines: list[list[dict]], anchors: list[str], allow_next_line: bool = True) -> list[dict]:
    """Name fields aren't a regex pattern: the value is whatever text follows
    the anchor phrase (e.g. "Bên cung ứng dịch vụ") on the same line, or the
    whole next line if nothing follows there.

    Each anchor is a normalized, space-separated phrase (e.g. "ben cung ung
    dich vu"); it's matched as a contiguous run of words whose normalized
    text equals the anchor's tokens exactly. A match only counts when it
    sits in a labeled/signature context (`_is_labeled_anchor`) -- without
    that guard, a phrase that recurs throughout ordinary contract prose (as
    "Bên Cung Ứng Dịch Vụ" does) would emit dozens of garbage sources, and
    since the reviewer's compare check takes the worst verdict across all
    sources, that noise would make even a correct name render as a mismatch.

    Once a match sits in a genuinely labeled context, it's worth a source
    either way (#008): if the value looks like a person's name
    (`_looks_like_person_name`) -> a readable hit with that value; else --
    handwritten/illegible, or nothing OCR'd there at all -- a located-but-
    unread ("cần xem") hit at the geometric value slot (`_geometric_value_slot`,
    shared with #005's pattern-field fallback), so the document's name is
    still navigable rather than silently missing. The labeled-context guard
    is what keeps this scoped: a prose mid-sentence mention never reaches
    this point at all. Results are deduped by value and capped
    (`_dedupe_and_cap`).

    #011 adds two things on top of that, both about WHICH PARTY a labeled
    occurrence names -- see the "Party columns" section above:

    - the value may be extended by the label's own REASSEMBLED ROW
      (`_row_words`), but only as a strict prefix extension
      (`_row_value_extension`). Measured on abs page 85 (packet 9's biên bản):
      `group_lines` split 'BÊN CUNG ỨNG DỊCH VỤ : Bùi Quang Vinh' so that
      'Phát' landed in a different fragment, and the truncated read 'Nhan
      Kiến' is a hard mismatch rather than a near miss -- `compare_values`
      `_person_verdict` makes a differing token count an outright MISMATCH.
    - on a page whose own column header marks off the two parties' columns
      (`_party_column_blocks`), a readable name is classified against that
      divide: the CTV's column -> `_RANK_PARTY_CERTAIN`; VNG's -> not a source
      at all (VNG's signatory is not evidence about the CTV, the same reasoning
      the `mst` spec uses to exclude the generic "Mã số thuế" anchor); and
      crossing it -> degraded to a located-but-unread hit, since a value
      spliced across the divide belongs to neither party (abs page 275 read
      'Văn Họ' -- one party's middle name token plus the first word of the
      other column's LABEL). Inside such a block a SECOND labeled occurrence
      on the same visual row is emitted too -- that is where the CTV's own name
      lives on abs page 275, which no single `group_lines` line contains -- but
      only when the divide places it in the CTV's column: with no party
      evidence an extra candidate would just be another confident guess.
    """
    hits = []
    tokenized = [a.split() for a in anchors]
    blocks = _party_column_blocks(lines)
    for idx, line in enumerate(lines):
        row = _row_words(lines, idx)
        occurrences = _anchor_occurrences(row, tokenized)
        primary = _primary_anchor_match(line, tokenized)
        if primary is not None:
            hit = _primary_name_hit(
                lines, idx, row, primary, anchors, tokenized, occurrences,
                allow_next_line, blocks)
            if hit is not None:
                hits.append(hit)
        primary_word = line[primary[0]] if primary is not None else None
        for i, n, a_idx in occurrences:
            # An occurrence belongs to whichever line holds its first label
            # word, so a row shared by several lines isn't processed twice --
            # and the line's own primary occurrence, handled above, is skipped.
            if row[i] is primary_word or not any(row[i] is w for w in line):
                continue
            hit = _extra_column_name_hit(
                row, i, n, a_idx, anchors, occurrences, blocks, lines)
            if hit is not None:
                hits.append(hit)
    return _dedupe_and_cap(hits)


# ---------------------------------------------------------------------------
# Document segmentation (#003) — classify each packet page by its title text,
# then group consecutive pages into documents.
# ---------------------------------------------------------------------------

# (keyword, kind, label) — first row whose keyword appears wins. `kind` is
# one of src/ctv/types.ts's EvidenceKind; "bbnt" is shared by nghiệm thu /
# thanh lý hợp đồng since the type enum doesn't distinguish them -- the label
# is what tells them apart in the reviewer. More specific keywords are listed
# before the generic "bien ban"/"cam ket" catch-alls they're a substring-
# superset of (a real title like "BIÊN BẢN NGHIỆM THU VÀ THANH LÝ HỢP ĐỒNG"
# contains "bien ban" too, but should resolve to the more specific label).
# Specific titles first, loose keywords next. Order is load-bearing: every one
# of these documents can carry "hợp đồng dịch vụ" in its own heading -- a
# `Biên bản thanh lý hợp đồng dịch vụ` is a BBNT, not a contract -- and the
# generic phrase used to sit first and win, mislabelling all three.
_PAGE_KEYWORDS: list[tuple[str, str, str]] = [
    ("thanh ly hop dong", "bbnt", "Biên bản thanh lý hợp đồng"),
    ("nghiem thu", "bbnt", "Biên bản nghiệm thu"),
    ("ban cam ket", "commitment", "Bản cam kết"),
    # "appendix" (not "pit") per #010 -- Phụ lục (an SOW/KPI evaluation
    # appendix) is its own document type, distinct from the tax-lookup
    # ("pit") docs it used to share a kind with.
    ("phu luc", "appendix", "Phụ lục"),
    ("bang thong tin tra cuu", "pit", "Tra cứu thuế"),
    ("nguoi nop thue tncn", "pit", "Tra cứu thuế"),
    ("can cuoc cong dan", "id_front", "CCCD"),
    # Before the contract rule: these name what the page *is*, while
    # "hợp đồng dịch vụ" may only be what it *cites*. Page 45 of the PUBGm
    # submission is a BBNT whose title OCR scrambled, and whose next line reads
    # "Căn cứ Hợp Đồng Dịch Vụ số đã ký" -- it classified as a contract, which
    # put a false packet start and a two-page packet in the split. A false
    # `contract` is the expensive direction: it invents a boundary, where a
    # false `bbnt` only means a boundary is not found and the cover stays put.
    ("bien ban", "bbnt", "Biên bản nghiệm thu"),
    ("cam ket", "commitment", "Bản cam kết"),
    ("hop dong dich vu", "contract", "Hợp đồng dịch vụ"),
    ("tra cuu", "pit", "Tra cứu thuế"),
]

#: Last resort: a heading whose *tokens* name a document, in any order and with
#: words missing. The July contract's first page really reads
#:
#:     ĐÔNG
#:     HỢP DỊCH VỤ
#:
#: because Tesseract hoists `ĐỒNG` out of `HỢP ĐỒNG DỊCH VỤ` onto its own line.
#: No phrase keyword can match that, so every contract first page went
#: unclassified -- which is what put the splitter's packet boundaries three
#: pages into each packet. Checked after every phrase rule above, so a title
#: that names itself precisely still wins.
_TITLE_TOKEN_RULES: list[tuple[frozenset[str], str, str]] = [
    (frozenset({"hop", "dich", "vu"}), "contract", "Hợp đồng dịch vụ"),
]

#: A token set matches far more loosely than a phrase, so it needs a tighter
#: shape test than `_TITLE_MAX_WORDS`. Real mid-contract lines on pages 11 and
#: 19 -- "Trả cho Bên Cung Dịch Vụ theo định tại Hợp" -- are nine words and
#: slipped under the ten-word cap, splitting one contract into three. The title
#: forms this rule exists for are three or four words.
_TITLE_TOKEN_MAX_WORDS = 5

# #009: two document types whose title/heading band is often too noisy or
# nonstandard for the heading-shaped-line check above to catch reliably --
# a tax-lookup screenshot's identifying text is frequently buried in banner/
# UI-chrome noise (not a clean short title line), and a cam-kết's own
# "BẢN CAM KẾT" heading can get merged/garbled by OCR. Their OWN markers
# below are distinctive enough to search ANYWHERE on the page -- not just a
# heading-shaped line -- because they never appear in ordinary contract/
# biên-bản prose, unlike the ambiguous, frequently-repeated "biên bản"/
# "hợp đồng" titles that the #003 guard above exists to protect (those stay
# heading-restricted; this relaxed check is intentionally scoped to just
# these two marker sets, checked only when the heading-restricted keywords
# above found nothing -- see `classify_page`).
_FULL_PAGE_MARKERS: list[tuple[list[str], str, str]] = [
    (["ban cam ket", "08/ck-tncn", "mau so: 08"], "commitment", "Bản cam kết"),
    # #012: "co quan thue" dropped -- every contract's own Điều 2 TTNCN-
    # withholding clause says "...trích nộp cho Cơ quan Thuế trước khi thanh
    # toán..."; when that clause happens to land on one long OCR line (no
    # hanging-indent line break splitting "quan" from "Thuế"), this marker
    # matched it and mis-started a `pit` document on the contract's own body
    # (measured on packets 8/15/16 of the July case). The other three
    # markers below are portal-specific ("Thông tin về người nộp thuế TNCN",
    # "Bảng thông tin tra cứu", the gdt.gov.vn URL) and were never observed
    # to false-fire; every genuine tax-lookup page in the July/February
    # audit was still caught by at least one of them.
    (["bang thong tin tra cuu", "thong tin ve nguoi nop thue", "tra cuu thong tin",
      "gdt.gov.vn"], "pit", "Tra cứu thuế"),
    # #010: a rotated Phụ lục (SOW/KPI evaluation appendix) OCRs with a
    # noisy/garbled title band even once upright (the surrounding table text
    # is itself low-quality) -- these markers catch it wherever they land.
    # #012: "phu luc" dropped from this list -- a contract routinely refers
    # to its own attachment in passing ("...cụ thể tại Phụ lục đính kèm."),
    # and that reference mis-started an `appendix` document on packet 5 of
    # the July case. A genuine (even rotated/garbled) Phụ lục title is still
    # caught either by the heading-shaped `_PAGE_KEYWORDS` "phu luc" rule
    # above (classify_page tries that first) or by the other three,
    # non-generic markers here -- measured directly on a real rotated
    # appendix page (July packet 5) whose garbled title missed "phu luc" but
    # still matched "danh gia chat luong dich vu", and on a February
    # appendix page whose table matched "sow".
    (["danh gia chat luong dich vu", "sow", "kpi"], "appendix", "Phụ lục"),
]

# A real document title is a short, standalone heading line (occasionally
# wrapped across two consecutive short lines, e.g. "BIÊN BẢN" / "NGHIỆM THU
# VÀ THANH LÝ HỢP ĐỒNG"). Real contract prose constantly *mentions* a
# document's own name in passing ("...theo quy định tại Điều 2 của Biên Bản
# này, Hợp Đồng sẽ được thanh lý...") -- those sentences run well past this
# length, which is what keeps such a mention from being mistaken for a title.
_TITLE_MAX_WORDS = 10


def _flatten(s: str) -> str:
    """Collapse all whitespace (incl. newlines from wrapped OCR lines) to single spaces."""
    return re.sub(r"\s+", " ", s)


def _top_slice(text: str) -> str:
    """The top ~1/3 of a page's lines (where titles/covers live)."""
    lines = text.splitlines() or [text]
    top_n = max(1, len(lines) // 3)
    return "\n".join(lines[:top_n])


def _title_candidates(lines: list[str]) -> list[str]:
    """Short, heading-shaped strings from a run of OCR lines: each short
    line alone, plus each pair of consecutive short lines joined (a title
    sometimes wraps across two lines) -- long lines never participate, which
    is what rejects a body-prose sentence that merely mentions a document's
    own name in passing (see `_TITLE_MAX_WORDS`).

    #012: word count alone is not a strong enough shape test -- a numbered
    contract clause routinely wraps into an OCR line short enough to slip
    under this cap. Callers additionally require `_looks_like_heading` on
    each candidate before treating it as a real title.
    """
    short = [i for i, line in enumerate(lines) if 0 < len(line.split()) <= _TITLE_MAX_WORDS]
    short_set = set(short)
    candidates = [lines[i] for i in short]
    candidates += [lines[i] + " " + lines[i + 1] for i in short if i + 1 in short_set]
    return candidates


def _looks_like_heading(candidate: str) -> bool:
    """Whether a `_title_candidates` string is shaped like a real printed
    title, not just short enough to be one.

    #012: every genuine title observed across the July and February
    submissions is set in full capitals (these templates print headings in
    block caps) -- including ones OCR mangles, e.g. "HỢP DỊCH VỤ" for a
    contract cover. Ordinary Vietnamese legal prose, by contrast, Title-Cases
    its own defined terms ("Biên Bản", "Hợp Đồng") but is not full-caps, even
    when a sentence about them is short. Two real OCR fragments found on
    packets that mis-segmented as a result (July case `68ddc1f0`, both short
    enough to pass `_TITLE_MAX_WORDS`, both containing a document keyword as
    an ordinary defined-term mention rather than a title):

        "của Hợp Đồng và được VNG ý nghiệm thu. Trong"   (packet 35, p1)
        "quy 2 của Biên Bản này, Hợp sẽ"                  (packet 9, p5)

    `str.isupper()` rejects both (correctly) while still accepting every
    real title in the corpus, including ones with digits/punctuation
    ("BẰNG THÔNG TIN TRA CỨU:") and Vietnamese diacritics (composed
    upper-case code points, e.g. "PHỤ LỤC ĐÁNH GIÁ CHẤT LƯỢNG DỊCH VỤ") --
    `isupper()` only requires every *cased* character to be upper-case, so
    digits/punctuation/whitespace don't disqualify a candidate.
    """
    return candidate.isupper()


def classify_page(text: str) -> tuple[str, str] | None:
    """Classify one page's OCR text by title keyword -> (kind, label), or
    None for a continuation/body page with no recognizable title.

    Checks the top ~1/3 of the page's lines first (titles/covers live there),
    then falls back to the whole page -- a title pushed down by OCR noise
    (e.g. banner/UI chrome above a tax-lookup results title) still gets
    picked up, but a keyword found only outside the top is a weaker signal
    than one at the top (see `segment_docs`, which uses that distinction to
    avoid false-starting a new document on a boilerplate closing clause).
    Only short, heading-shaped lines are considered (`_title_candidates`,
    gated by `_looks_like_heading` -- #012), so a keyword mentioned in
    passing within ordinary body prose is ignored even when the OCR line
    happens to be short.

    #009: if neither pass matches, a last check searches the WHOLE page text
    -- unrestricted by line length/shape/case -- for `_FULL_PAGE_MARKERS`,
    since a tax-lookup screenshot or a cam-kết page's identifying text
    doesn't always land in a clean heading-shaped line. This stays scoped to
    just those marker sets (distinctive enough to be safe anywhere, #012
    having trimmed the two that weren't -- see `_FULL_PAGE_MARKERS`); the
    ambiguous, frequently-repeated "biên bản"/"hợp đồng" titles above are
    untouched.
    """
    lines = text.splitlines() or [text]
    top_n = max(1, len(lines) // 3)
    for line_group in (lines[:top_n], lines):
        candidates = [
            _flatten(norm(c)) for c in _title_candidates(line_group) if _looks_like_heading(c)
        ]
        for kw, kind, label in _PAGE_KEYWORDS:
            if any(kw in c for c in candidates):
                return kind, label
    for line_group in (lines[:top_n], lines):
        for candidate in _title_candidates(line_group):
            if not _looks_like_heading(candidate):
                continue
            tokens = _flatten(norm(candidate)).split()
            if len(tokens) > _TITLE_TOKEN_MAX_WORDS:
                continue
            for needed, kind, label in _TITLE_TOKEN_RULES:
                if needed <= set(tokens):
                    return kind, label

    whole_page = _flatten(norm(text))
    for markers, kind, label in _FULL_PAGE_MARKERS:
        if any(m in whole_page for m in markers):
            return kind, label
    return None


def segment_docs(page_texts: list[str]) -> list[dict]:
    """Group a packet's pages (in order) into documents by title.

    A page whose text classifies starts a new document; an unclassified page
    is a continuation of the current document. If the very first page is
    unclassified, a default `contract` document opens to hold it (and
    whatever follows, until a real title page starts a new one).

    Exception: if a page classifies to the SAME (kind, label) as the
    document already open, but only via the whole-page fallback (not the
    top ~1/3) -- e.g. a closing clause like "Biên bản này được lập thành 02
    bản..." repeating the document's own name near the bottom of its last
    page -- it's treated as a continuation, not a new document. A real
    second same-kind/-label document's title still lives in ITS OWN top
    ~1/3, so this only suppresses the weak, self-referential false
    positive.

    Returns `[{kind, label, pages: [packet-relative indices]}, ...]`.
    """
    docs: list[dict] = []
    current: dict | None = None
    for i, text in enumerate(page_texts):
        classified = classify_page(text)
        if classified is not None:
            if current is not None and (current["kind"], current["label"]) == classified:
                matched_in_top = classify_page(_top_slice(text)) == classified
                if not matched_in_top:
                    current["pages"].append(i)
                    continue
            kind, label = classified
            current = {"kind": kind, "label": label, "pages": [i]}
            docs.append(current)
        elif current is not None:
            current["pages"].append(i)
        else:
            current = {"kind": "contract", "label": "Hợp đồng dịch vụ", "pages": [i]}
            docs.append(current)
    return docs


# ---------------------------------------------------------------------------
# Field assembly (Task A3)
# ---------------------------------------------------------------------------

FIELD_SPECS = [
    {
        # "ten toi la" (Bản cam kết's "Tên tôi là:") and "ho va ten" (generic
        # "Họ và tên" label) added per #008 -- the name was only found on the
        # Biên bản before, missing it on the cam kết and (readably) the contract.
        # "en toi la" additionally covers a real-packet OCR artifact found
        # verifying #008 on an actual scan: Tesseract dropped the leading "T"
        # of "Tên", reading the printed label as "ên tôi là" -- still safely
        # scoped by the same `_is_labeled_anchor` guard (ALL CAPS or a ':'
        # label), so it doesn't open the door to unrelated prose.
        "key": "hoten", "label": "Họ tên", "group": "Danh tính", "kind": "person",
        "anchors": ["ben cung ung dich vu", "ten nguoi nop thue", "ten toi la", "en toi la", "ho va ten"],
        "patterns": [], "roster_key": "name",
    },
    {
        "key": "cccd", "label": "Số CCCD", "group": "Danh tính", "kind": "text",
        # Keep identity-card evidence separate from the individual's tax ID.
        # Tesseract commonly drops the final consonant in the two-line
        # "Căn cước/Hộ chiếu số" label and renders printed "CCCD" with an œ.
        "anchors": ["can cuoc", "can cuoc ho", "can cuo ho", "so cccd", "cccd so", "cœccd so"],
        "patterns": [PATTERNS["CCCD_SPACED"], PATTERNS["MST"]], "roster_key": "cccd",
    },
    {
        # Anchored on the INDIVIDUAL tax-id label only (MSTTNCN), never the
        # bare "Mã số thuế"/"MST" -- that generic label also names VNG's own
        # company MST (on the "Bên sử dụng dịch vụ" block of every doc) and
        # the tax-lookup page's search box, both of which are NOT the
        # person's own tax id. Under worst-wins compare, either would
        # false-mismatch a correct value. MSTTNCN appears on the biên bản,
        # the contract, the cam kết (under "Tên tôi là"), and the tax-lookup
        # results row -- all individual-scoped.
        "key": "mst", "label": "Mã số thuế", "group": "Danh tính", "kind": "text",
        "anchors": ["msttncn", "ma so thue thu nhap ca nhan", "mst tncn", "ma so thue ca nhan"],
        "patterns": [PATTERNS["CCCD_SPACED"], PATTERNS["MST"]], "roster_key": "mst",
    },
    {
        "key": "tk", "label": "Số tài khoản", "group": "Ngân hàng", "kind": "text",
        "anchors": ["so tai khoan", "tk so"],
        "patterns": [PATTERNS["ACCOUNT"]], "roster_key": "tk",
    },
    {
        "key": "ngaysinh", "label": "Ngày sinh", "group": "Danh tính", "kind": "date",
        "anchors": ["ngay sinh"],
        "patterns": [PATTERNS["DATE"]], "roster_key": "ngaysinh",
    },
    {
        # `lookahead: 3` -- "phi dich vu" is the one anchor that matches a
        # SECTION HEADING ("ĐIỀU 2. PHÍ DỊCH VỤ VÀ THANH TOÁN") rather than the
        # value's own line, because OCR reads big bold type reliably while
        # routinely dropping "vụ" from the clause below ("Phí dịch 8.888.889
        # đồng."), so the clause never anchors itself. Measured on the July
        # batch: the fee sits 2-3 display-space lines under the heading, and a
        # 1-line lookahead read it on 32 of 41 packets only because the fee
        # happened to be the very next line -- an intervening OCR fragment
        # ("IÍ") broke the other 9. At 3 lines, 7 of those 9 are recovered.
        # MONEY needs a thousands separator, which is what keeps the wider
        # window from capturing a clause number or a page number.
        "key": "phi", "label": "Phí dịch vụ", "group": "Thanh toán", "kind": "number",
        "anchors": ["phi dich vu"], "lookahead": 3,
        "patterns": [PATTERNS["MONEY"]], "roster_key": "phi",
    },
]

_EMPTY_SOURCE = {"docId": "", "page": 0, "value": "", "bbox": {"x": 0, "y": 0, "width": 0, "height": 0}, "confidence": 0.0}


def _hits_for_doc(spec: dict, pages: dict[int, list[dict]]) -> list[tuple[int, dict]]:
    """Every `(page_idx, hit)` a field's spec produces across one document's
    pages: `find_name` for name fields (unchanged -- its labeled-context +
    person-name-shape guards are what keep it from flooding the name field
    with every mid-sentence mention of "Bên cung ứng dịch vụ"), `locate_field`
    (readable-or-"cần xem") for every other field.
    """
    hits = []
    for page_idx, words in pages.items():
        lines = group_lines(words)
        page_hits = (
            find_name(lines, spec["anchors"])
            if spec["kind"] in ("name", "person")
            else locate_field(lines, spec)
        )
        hits.extend((page_idx, h) for h in page_hits)
    return hits


def _best_hit(hits: list[tuple[int, dict]]) -> tuple[int, dict] | None:
    """The one hit a document contributes for a field (#004: a document gets
    exactly one source per field, never one per confirming/anchor line) --
    a readable value if the document has one; else a located-but-unread hit,
    still worth a navigable "cần xem" chip rather than no source at all.

    Within the pool the key is `_hit_rank`: party evidence first, confidence
    only as the tiebreak (#011 -- confidence is legibility, not correctness,
    and both parties' names print equally crisply). `locate_field`'s hits
    carry no "rank", so for the five pattern fields the key degenerates to the
    confidence-only one it replaced, and `max` still returns the first maximal
    element -- the same hit, ties included.
    """
    if not hits:
        return None
    readable = [ph for ph in hits if ph[1]["value"]]
    pool = readable or hits
    return max(pool, key=lambda ph: _hit_rank(ph[1]))


def extract_fields(words_by_doc: dict[str, dict[int, list[dict]]], roster_row: dict[str, str]) -> list[dict]:
    """Run every FIELD_SPECS entry over every document's OCR words, emitting
    ONE source per document whose label is present (#004 "locate & look"):
    readable occurrences carry a value + bbox + confidence (the hint verdict,
    as before); unreadable ones ("cần xem") carry `value=""`, the
    region-after-label bbox, and `confidence=0.0` -- still navigable, never a
    hard mismatch.

    `words_by_doc` is `{docId: {page_index: [scaled Word, ...]}}`. `expected`
    comes from `roster_row[roster_key]`; a field whose label appears in NO
    document still gets a single empty/zero-confidence source, so it reads
    as an exception to check rather than silently disappearing.
    """
    fields = []
    for spec in FIELD_SPECS:
        sources = []
        for doc_id, pages in words_by_doc.items():
            best = _best_hit(_hits_for_doc(spec, pages))
            if best is None:
                continue  # this field's label doesn't appear in this document
            page_idx, hit = best
            sources.append({
                "docId": doc_id,
                "page": page_idx,
                "value": hit["value"],
                "bbox": hit["bbox"],
                "confidence": hit["confidence"],
            })
        if not sources:
            sources = [dict(_EMPTY_SOURCE)]
        fields.append({
            "key": spec["key"],
            "label": spec["label"],
            "group": spec["group"],
            "check": "compare",
            "kind": spec["kind"],
            "expected": roster_row.get(spec["roster_key"], ""),
            "sources": sources,
        })
    return fields


def build_manifest(folder_id: str, name: str, product: str, docs: list[dict], fields: list[dict]) -> dict:
    """Assemble the CtvFolder dict (matches src/ctv/types.ts exactly)."""
    return {
        "id": folder_id,
        "name": name,
        "product": product,
        "heading": "Hồ sơ CTV",
        "status": "pending",
        "exempt": False,
        "docs": docs,
        "fields": fields,
    }


# ---------------------------------------------------------------------------
# Rotation-aware OCR (#010) — pure upright-angle decision logic. The OSD call
# itself (Tesseract's page orientation detector) is I/O (see
# `detect_page_rotation` below); this is the pure math around its result, so
# it's unit-testable without a real PDF/Tesseract.
# ---------------------------------------------------------------------------

# Tesseract OSD's `orientation_conf` below which its rotation guess is too
# unreliable to act on -- never rotate a page you're unsure about, since a
# wrongly-rotated portrait page would be worse than the (already correct)
# status quo. Chosen well below the real rotated page's observed ~8-10 and
# comfortably above the noise floor typical portrait pages report even when
# OSD (correctly) finds nothing to fix.
_MIN_OSD_CONF = 1.5


def _upright_rotation(osd_rotate: int, osd_conf: float, min_conf: float = _MIN_OSD_CONF) -> int:
    """The angle (degrees, PIL `Image.rotate`-style: positive = counter-
    clockwise) to apply to make a page upright, given Tesseract OSD's
    `rotate` (the CLOCKWISE angle OSD says the image needs) and its
    `orientation_conf` -- or `0` (no rotation) if `osd_rotate` isn't one of
    the 3 real rotations, or confidence is below `min_conf`.

    OSD's `rotate` and PIL's CCW-positive convention are opposite senses of
    the same turn, so the CCW angle to apply is `(360 - osd_rotate) % 360`
    (e.g. OSD `rotate=270` -> apply `+90` CCW -- verified against a real
    rotated page: `img.rotate(90, expand=True)` reads upright).
    """
    if osd_rotate not in (90, 180, 270) or osd_conf < min_conf:
        return 0
    return (360 - osd_rotate) % 360


# ---------------------------------------------------------------------------
# I/O layer (Task A4) — PyMuPDF render + pytesseract OCR. Not unit-tested
# (needs a real PDF + Tesseract); verified by running on real packets (A5).
# ---------------------------------------------------------------------------

def detect_page_rotation(pdf_path: str, page_index: int, osd_dpi: int = 150) -> int:
    """Detect a page's upright rotation (0/90/180/270, PIL CCW-style) via
    Tesseract OSD -- `0` if OSD errors (sparse/blank/unusual pages can throw),
    finds nothing to fix, or isn't confident (`_upright_rotation`). Never
    guesses: an unrotated page is always a safe fallback.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        zoom = osd_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
    except Exception:  # noqa: BLE001 - OSD can fail outright on some pages; never rotate on a guess
        return 0
    return _upright_rotation(osd.get("rotate", 0), osd.get("orientation_conf", 0.0))


def render_pages(
    pdf_path: str, start: int, end: int, out_dir: str, display_dpi: int = 150,
    rotations: dict[int, int] | None = None,
) -> list[dict]:
    """Render packet pages [start,end] (inclusive, 0-based) to PNGs in out_dir.

    `rotations` is `{rel_idx: degrees}` (PIL CCW angle, see
    `_upright_rotation`) -- a page with a detected non-upright orientation is
    rotated upright before saving, so the served PNG reads correctly (#010).
    Absent/0 for the vast majority of already-upright pages, which are saved
    byte-for-byte exactly as before.

    Returns `DocPage` dicts `{src, width, height}` in packet order (`width`/
    `height` are the UPRIGHT/post-rotation dimensions); `src` is the absolute
    PNG path (offline use — a server would rewrite this to a URL).
    """
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    zoom = display_dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    rotations = rotations or {}
    pages = []
    try:
        for rel_idx, page_num in enumerate(range(start, end + 1)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat)
            angle = rotations.get(rel_idx, 0)
            path = os.path.join(out_dir, f"pg{rel_idx}.png")
            if angle:
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).rotate(angle, expand=True)
                img.save(path)
                width, height = img.size
            else:
                pix.save(path)
                width, height = pix.width, pix.height
            pages.append({"src": path, "width": width, "height": height})
    finally:
        doc.close()
    return pages


def ocr_words(
    pdf_path: str, page_index: int, ocr_dpi: int = 300, display_dpi: int = 150,
    rotation: int = 0, band_frac: float = 1.0,
) -> tuple[list[dict], float]:
    """OCR one page (0-based, absolute index) at `ocr_dpi` with Tesseract `vie`.

    `band_frac` < 1.0 OCRs only the top fraction of the page. Coordinates stay
    valid (the crop is from the origin), and it is roughly three times faster --
    for a caller that only needs to know whether a document *starts* here, which
    its title answers at the top of the page. A cropped read will miss titles
    further down, so it is not a general classifier.

    `rotation` (PIL CCW degrees, see `_upright_rotation`) is applied to the
    OCR-dpi image before running Tesseract, so a rotated page's words come
    out in the SAME upright orientation as the matching `render_pages`
    (#010) -- the `display_dpi/ocr_dpi` scale factor below stays valid since
    both images are rotated by the same angle before that uniform scaling.

    Returns (words in OCR-pixel space, `display_dpi/ocr_dpi` scale factor) —
    the caller scales the words to display space with `scale_words`.
    """
    if not 0.0 < band_frac <= 1.0:
        raise ValueError(f"band_frac must be in (0, 1], got {band_frac!r}")
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        zoom = ocr_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    if rotation:
        img = img.rotate(rotation, expand=True)
    if band_frac < 1.0:
        img = img.crop((0, 0, img.width, max(1, int(img.height * band_frac))))
    data = pytesseract.image_to_data(img, lang="vie", output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        words.append({
            "text": text,
            "x": data["left"][i],
            "y": data["top"][i],
            "w": data["width"][i],
            "h": data["height"][i],
            "conf": conf,
        })
    return words, display_dpi / ocr_dpi


def _slug(name: str) -> str:
    """Filesystem/URL-safe id from a display name (lowercase, ascii, dashes)."""
    s = re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")
    return s or "folder"


def _page_text(words: list[dict]) -> str:
    """Plain reading-order text for one page's OCR words, for classify_page."""
    lines = group_lines(words)
    return "\n".join(" ".join(w["text"] for w in line) for line in lines)


def _best_value(field: dict) -> str:
    """The highest-confidence non-empty source value for one extracted field
    (used to derive the packet's OCR'd identity — see `ocr_packet`)."""
    candidates = [s for s in field["sources"] if s.get("value")]
    if not candidates:
        return ""
    return max(candidates, key=lambda s: s["confidence"])["value"]


def _escalate_weak_fields(
    fields: list[dict],
    page_reader,
    words_by_doc: dict[str, dict[int, list[dict]]],
    page_of: dict[tuple[str, int], int],
    pages: list[dict],
) -> list[dict]:
    """Re-read the pages whose fields the local reader could not resolve.

    Sends the DISPLAY png that is already rendered on disk, not a fresh
    high-dpi render: the returned boxes are then already in display space --
    the same space `words_by_page` holds and the same one the reviewer's
    highlight is drawn in -- so there is no scale factor to get wrong, and it
    is a smaller upload.

    Local words stay the fallback at every step. A page the reader fails on, a
    page it returns nothing for, and a reader that raises are all left with
    their local read, because a network problem must never make an ingest worse
    than not having called at all.
    """
    from field_escalation import merge_sources, plan   # local: keeps import light

    decision = plan(fields)
    if not decision.worth_calling:
        return fields

    reread: dict[tuple[str, int], list[dict]] = {}
    for doc_id, doc_page in decision.pages:
        pk = page_of.get((doc_id, doc_page))
        if pk is None or pk >= len(pages):
            continue
        src = pages[pk].get("src") or ""
        if not src or not os.path.exists(src):
            continue
        try:
            with open(src, "rb") as handle:
                words = page_reader(handle.read(), os.path.basename(src))
        except Exception:
            continue
        if words:
            reread[(doc_id, doc_page)] = words

    if not reread:
        return fields

    swapped = {doc: dict(by_page) for doc, by_page in words_by_doc.items()}
    for (doc_id, doc_page), words in reread.items():
        swapped.setdefault(doc_id, {})[doc_page] = words
    return merge_sources(fields, extract_fields(swapped, {}), set(reread))


# ---------------------------------------------------------------------------
# Where the contractor's name could be (#01), recorded during the read
# ---------------------------------------------------------------------------

#: How far from an identity label a line is still a candidate for the
#: contractor's name, in multiples of that label line's own height. Measured in
#: line-heights rather than line indices for the reason `group_lines` makes
#: obvious: index distance ignores whitespace, so "three lines above" can be
#: three lines up or half a page up. A contractor block prints the name within
#: about three lines of the ID number; VNG's signatory is printed far from it.
_NAME_CANDIDATE_HEIGHTS = 5

#: Longest line kept. A manifest-size guard rather than a name heuristic -- the
#: manifest is read on every request -- and a printed name line is short.
_NAME_CANDIDATE_CHARS = 80

#: Most lines kept per document, nearest to a label first. Measured on case
#: `935e37e5` after a cap of 8 left #01 pending on three BBNTs that plainly
#: carried the name: a BBNT labels the identity block twice, so 7-16 lines fall
#: within reach and the name line -- 4.5-4.9 line-heights out -- sat below the
#: eight nearest. At 111 bytes a line this costs ~2.7 KB per document, against
#: a manifest that is ~8 KB without it.
_MAX_NAME_CANDIDATES = 24


def _identity_anchors() -> list[str]:
    """The labels marking the individual's own identity block.

    Both the CCCD's and the personal MST's: the `mst` spec records that its
    MSTTNCN label survives OCR where the CCCD label sometimes does not, and
    either lands on the same block. Read off `FIELD_SPECS` rather than copied,
    so a label added there is found here too.
    """
    return [anchor for spec in FIELD_SPECS if spec["key"] in ("cccd", "mst")
            for anchor in spec["anchors"]]


def name_candidates(pages: dict[int, list[dict]]) -> list[dict]:
    """`[{"page", "text", "bbox"}]` -- the lines near this document's identity
    labels, for #01 to look for the bảng kê's name in later.

    #01 is the one field that cannot be discovered. It has no shape (`hoten` is
    the only `FIELD_SPECS` entry with `"patterns": []`), and on a real contract
    no label says whose the name on the bare line is -- the contractor's looks
    exactly like VNG's signatory printed two lines above. So this records only
    *where a name could be* and leaves *which name* to
    `confirm_expected.confirm_name`, once `pipeline.match_roster` has
    established who the packet belongs to.

    It has to happen during the read, for the same reason `signature_anchors`
    and `semantic_read` do it: the saved manifest keeps only
    `{src, width, height}` per page, so there are no words left to search
    afterwards. And it stays a handful of short lines rather than the page's
    words, because the manifest is read on every request.
    """
    anchors = _identity_anchors()
    found: list[tuple[float, dict]] = []
    for page, words in sorted(pages.items()):
        lines = group_lines(words)
        boxes = [union_bbox(line) for line in lines]
        labelled = [
            i for i, line in enumerate(lines)
            if any(_anchor_word_span(line, a) for a in anchors)
        ]
        if not labelled:
            continue
        for j, line in enumerate(lines):
            gap = min(abs(boxes[j]["y"] - boxes[i]["y"])
                      / max(1, boxes[i]["height"]) for i in labelled)
            if gap > _NAME_CANDIDATE_HEIGHTS:
                continue
            text = " ".join(w["text"] for w in line).strip()
            if not text or len(text) > _NAME_CANDIDATE_CHARS:
                continue
            found.append((gap, {"page": page, "text": text, "bbox": boxes[j]}))
    found.sort(key=lambda pair: pair[0])
    return [candidate for _, candidate in found[:_MAX_NAME_CANDIDATES]]


def assemble_docs(
    segments: list[dict],
    pages: list[dict],
    words_by_page: dict[int, list[dict]],
) -> tuple[list[dict], dict[str, dict[int, list[dict]]], dict[tuple[str, int], int]]:
    """Turn segmented pages into `(docs, words_by_doc, page_of)`.

    Pulled out of `ocr_packet` so it can be tested at all: nothing calls
    `ocr_packet` in the suite -- it needs a real PDF and a page reader -- while
    everything this returns is decided here, from data a test can build.

    Each doc records where each party signs (`anchors`), because the words are
    only in hand during the read: the saved manifest keeps `{src, width, height}`
    per page and nothing else, so a criterion evaluated later has nothing left
    to search.
    """
    from signature_anchors import find_anchors  # lazy: it imports this module

    docs: list[dict] = []
    words_by_doc: dict[str, dict[int, list[dict]]] = {}
    #: (docId, page-within-doc) -> page index within the packet, so an
    #: escalation can find the rendered PNG for a page a field points at.
    page_of: dict[tuple[str, int], int] = {}
    kind_counts: dict[str, int] = {}
    for seg in segments:
        n = kind_counts.get(seg["kind"], 0)
        kind_counts[seg["kind"]] = n + 1
        doc_id = f"{seg['kind']}-{n}"
        docs.append({
            "id": doc_id,
            "kind": seg["kind"],
            "label": seg["label"],
            "pages": [pages[pk] for pk in seg["pages"]],
        })
        words_by_doc[doc_id] = {
            j: words_by_page[pk] for j, pk in enumerate(seg["pages"])
        }
        page_of.update({(doc_id, j): pk for j, pk in enumerate(seg["pages"])})
        # Set on every document this function builds, `{}` when nothing matched:
        # a missing key and "no signature block found" are different answers.
        # Not a guarantee across the whole manifest, though -- `cccd_ingest`
        # attaches the card documents afterwards and they carry no `anchors` at
        # all (14 of them on a real 25-packet case). Harmless, because no
        # signature criterion looks at a card and `evaluate._block_evidence`
        # reads this with `.get("anchors") or {}` -- but a reader must not take
        # the key as always present.
        docs[-1]["anchors"] = find_anchors(
            words_by_doc[doc_id],
            {j: pages[pk].get("height") for j, pk in enumerate(seg["pages"])},
        )
        # Same reason as `anchors` above, and the same caveat: `cccd_ingest`
        # attaches card documents afterwards that carry no `nameCandidates`
        # key, so a reader must use `.get(...) or []`.
        docs[-1]["nameCandidates"] = name_candidates(words_by_doc[doc_id])
    return docs, words_by_doc, page_of


def ocr_packet(
    pdf_path: str,
    start: int,
    end: int,
    out_dir: str,
    display_dpi: int = 150,
    ocr_dpi: int = 300,
    page_reader=None,
) -> dict:
    """Render + OCR + segment one packet's page range.

    Writes the page PNGs (via render_pages) into `out_dir` and returns
    `{"folder": {"docs": [...], "fields": [...]}, "identity": {"cccd", "name"}}`.

    Pages are segmented into documents by title (`segment_docs`); each field
    source's `docId`/`page` point at the owning document (page index relative
    to that document, matching `docs[].pages[]`). `fields[].expected` is left
    empty here — identity (which roster row this packet belongs to) isn't
    known until the caller matches `identity` against the roster
    (`pipeline.match_roster`) and fills expected values in
    (`pipeline.fill_expected`) before writing the manifest.

    `page_reader`, when given, is a `(image_bytes, filename) -> words` callable
    (see `idp_words.reader`) used to RE-READ only the pages whose fields the
    local reader could not resolve -- see `_escalate_weak_fields`. None means
    local-only, which is the default: no page leaves the workstation unless a
    caller supplies a reader.

    #010: each page's rotation is detected once (`detect_page_rotation`) and
    applied consistently to BOTH the served display PNG and the OCR image,
    so a rotated page (e.g. a landscape SOW/KPI appendix scanned sideways)
    reads upright in the reviewer and OCRs correctly, instead of garbling.
    """
    os.makedirs(out_dir, exist_ok=True)
    rotations = {
        rel_idx: angle
        for rel_idx, abs_page in enumerate(range(start, end + 1))
        if (angle := detect_page_rotation(pdf_path, abs_page, osd_dpi=display_dpi))
    }
    pages = render_pages(pdf_path, start, end, out_dir, display_dpi=display_dpi, rotations=rotations)

    words_by_page: dict[int, list[dict]] = {}
    for rel_idx, abs_page in enumerate(range(start, end + 1)):
        words, factor = ocr_words(
            pdf_path, abs_page, ocr_dpi=ocr_dpi, display_dpi=display_dpi,
            rotation=rotations.get(rel_idx, 0),
        )
        words_by_page[rel_idx] = scale_words(words, factor)

    page_texts = [_page_text(words_by_page[i]) for i in range(len(pages))]
    segments = segment_docs(page_texts)

    docs, words_by_doc, page_of = assemble_docs(
        segments, pages, words_by_page,
    )

    fields = extract_fields(words_by_doc, {})
    if page_reader is not None:
        fields = _escalate_weak_fields(
            fields, page_reader, words_by_doc, page_of, pages,
        )
    by_key = {f["key"]: f for f in fields}
    identity = {
        "cccd": _best_value(by_key["cccd"]),
        # The personal MST is a strong identifier in its own right, and its
        # `MSTTNCN` label survives OCR where the CCCD label sometimes does not.
        # `pipeline.match_roster` tries it between the CCCD and the name.
        "mst": _best_value(by_key["mst"]),
        "name": _best_value(by_key["hoten"]),
    }

    return {"folder": {"docs": docs, "fields": fields}, "identity": identity}
