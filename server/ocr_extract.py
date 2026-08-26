"""Extract key fields (with bboxes) from an OCR'd PDF packet into a CtvFolder manifest.

Pure geometry/text logic (scale, line grouping, bbox union, diacritic-insensitive
normalization, anchored pattern search, field assembly) is unit-tested on
synthetic OCR word lists — no PDF/Tesseract needed. The I/O layer (PyMuPDF
render + pytesseract) is verified by running on real packets (see
docs/superpowers/specs/2026-07-13-upload-split-ocr-validate-design.md).

Output shape matches src/ctv/types.ts exactly (CtvFolder/EvidenceDoc/DocPage/
CtvField/CtvSource) so manifests load straight into the existing reviewer.
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


def locate_field(lines: list[list[dict]], spec: dict) -> list[dict]:
    """For each line whose text contains one of `spec["anchors"]` (accent-
    insensitively), produce exactly one hit -- never zero for a matching
    line, never more than one -- so a field's LOCATION is found even when
    its value can't be read (e.g. handwritten):

    - if any of `spec["patterns"]` matches this line (or, failing that, the
      next line -- same lookahead as `find_in_lines`) -> a readable hit:
      `{value, bbox, confidence}` from the matched words;
    - else -> a located-but-unread hit: `value=""`, `bbox` = the value slot
      on this line (see `_label_region_bbox`), `confidence=0.0`.

    This is the "locate & look" fix for docs/test-findings.md #004: a label
    reliably found is worth a navigable "cần xem" chip even when its
    handwritten value isn't -- the OCR'd value is a hint, never the gate.
    """
    anchors_norm = [norm(a) for a in spec["anchors"]]
    patterns = spec.get("patterns", [])
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
            if hit is None and idx + 1 < len(lines):
                hit = _search_line(lines[idx + 1], pattern)
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


def _dedupe_and_cap(hits: list[dict], max_n: int = 3) -> list[dict]:
    """Collapse identical values to their highest-confidence hit; keep at
    most `max_n`, highest-confidence first -- so a handful of genuine
    labeled occurrences don't get diluted by noise, and duplicates don't
    inflate the source count.
    """
    best_by_value: dict[str, dict] = {}
    for h in hits:
        prev = best_by_value.get(h["value"])
        if prev is None or h["confidence"] > prev["confidence"]:
            best_by_value[h["value"]] = h
    ordered = sorted(best_by_value.values(), key=lambda h: -h["confidence"])
    return ordered[:max_n]


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
    """
    hits = []
    tokenized = [a.split() for a in anchors]
    for idx, line in enumerate(lines):
        words_norm = [_clean_tok(norm(w["text"])) for w in line]
        match = None
        for tokens in tokenized:
            n = len(tokens)
            for i in range(len(words_norm) - n + 1):
                if words_norm[i:i + n] == tokens:
                    match = (i, n)
                    break
            if match is not None:
                break
        if match is None:
            continue
        i, n = match
        if not _is_labeled_anchor(line, i, n):
            continue
        value_words = line[i + n:]
        if value_words and value_words[0]["text"].strip() == ":":
            value_words = value_words[1:]
        if not value_words and allow_next_line and idx + 1 < len(lines):
            value_words = lines[idx + 1]
        if value_words and _looks_like_person_name(value_words):
            hits.append({
                "value": " ".join(w["text"] for w in value_words),
                "bbox": union_bbox(value_words),
                "confidence": min(w["conf"] for w in value_words) / 100,
            })
        else:
            hits.append({
                "value": "",
                "bbox": _geometric_value_slot(line, line[i:i + n], i + n, lines),
                "confidence": 0.0,
            })
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
    (["bang thong tin tra cuu", "thong tin ve nguoi nop thue", "tra cuu thong tin",
      "gdt.gov.vn", "co quan thue"], "pit", "Tra cứu thuế"),
    # #010: a rotated Phụ lục (SOW/KPI evaluation appendix) OCRs with a
    # noisy/garbled title band even once upright (the surrounding table text
    # is itself low-quality) -- these markers catch it wherever they land.
    (["phu luc", "danh gia chat luong dich vu", "sow", "kpi"], "appendix", "Phụ lục"),
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
    """
    short = [i for i, line in enumerate(lines) if 0 < len(line.split()) <= _TITLE_MAX_WORDS]
    short_set = set(short)
    candidates = [lines[i] for i in short]
    candidates += [lines[i] + " " + lines[i + 1] for i in short if i + 1 in short_set]
    return candidates


def classify_page(text: str) -> tuple[str, str] | None:
    """Classify one page's OCR text by title keyword -> (kind, label), or
    None for a continuation/body page with no recognizable title.

    Checks the top ~1/3 of the page's lines first (titles/covers live there),
    then falls back to the whole page -- a title pushed down by OCR noise
    (e.g. banner/UI chrome above a tax-lookup results title) still gets
    picked up, but a keyword found only outside the top is a weaker signal
    than one at the top (see `segment_docs`, which uses that distinction to
    avoid false-starting a new document on a boilerplate closing clause).
    Only short, heading-shaped lines are considered (`_title_candidates`),
    so a keyword mentioned in passing within ordinary body prose is ignored.

    #009: if neither pass matches, a last check searches the WHOLE page text
    -- unrestricted by line length/shape -- for `_FULL_PAGE_MARKERS`, since a
    tax-lookup screenshot or a cam-kết page's identifying text doesn't always
    land in a clean heading-shaped line. This stays scoped to just those two
    marker sets (distinctive enough to be safe anywhere); the ambiguous,
    frequently-repeated "biên bản"/"hợp đồng" titles above are untouched.
    """
    lines = text.splitlines() or [text]
    top_n = max(1, len(lines) // 3)
    for line_group in (lines[:top_n], lines):
        candidates = [_flatten(norm(c)) for c in _title_candidates(line_group)]
        for kw, kind, label in _PAGE_KEYWORDS:
            if any(kw in c for c in candidates):
                return kind, label
    for line_group in (lines[:top_n], lines):
        for candidate in _title_candidates(line_group):
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
        "key": "phi", "label": "Phí dịch vụ", "group": "Thanh toán", "kind": "number",
        "anchors": ["phi dich vu"],
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
    a readable value (highest confidence) if the document has one; else a
    located-but-unread hit, still worth a navigable "cần xem" chip rather
    than no source at all.
    """
    if not hits:
        return None
    readable = [ph for ph in hits if ph[1]["value"]]
    pool = readable or hits
    return max(pool, key=lambda ph: ph[1]["confidence"])


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


def ocr_packet(
    pdf_path: str,
    start: int,
    end: int,
    out_dir: str,
    display_dpi: int = 150,
    ocr_dpi: int = 300,
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

    docs: list[dict] = []
    words_by_doc: dict[str, dict[int, list[dict]]] = {}
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

    fields = extract_fields(words_by_doc, {})
    by_key = {f["key"]: f for f in fields}
    identity = {
        "cccd": _best_value(by_key["cccd"]),
        "name": _best_value(by_key["hoten"]),
    }

    return {"folder": {"docs": docs, "fields": fields}, "identity": identity}
