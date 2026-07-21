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
    sits in a labeled/signature context (`_is_labeled_anchor`) and the
    candidate value looks like a person's name (`_looks_like_person_name`) --
    without both guards, a phrase that recurs throughout ordinary contract
    prose (as this one does) would emit dozens of garbage sources, and since
    the reviewer's compare check takes the worst verdict across all sources,
    that noise would make even a correct name render as a mismatch. Results
    are deduped by value and capped (`_dedupe_and_cap`).
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
        if not value_words:
            continue
        if not _looks_like_person_name(value_words):
            continue
        hits.append({
            "value": " ".join(w["text"] for w in value_words),
            "bbox": union_bbox(value_words),
            "confidence": min(w["conf"] for w in value_words) / 100,
        })
    return _dedupe_and_cap(hits)


# ---------------------------------------------------------------------------
# Document segmentation (#003) — classify each packet page by its title text,
# then group consecutive pages into documents.
# ---------------------------------------------------------------------------

# (keyword, kind, label) — first row whose keyword appears wins. `kind` is
# one of src/ctv/types.ts's EvidenceKind; several rows share a kind ("bbnt":
# nghiệm thu / thanh lý hợp đồng; "pit": Phụ lục / Tra cứu thuế) since the
# type enum doesn't distinguish them -- the label is what tells them apart in
# the reviewer. More specific keywords are listed before the generic "bien
# ban"/"cam ket" catch-alls they're a substring-superset of (a real title
# like "BIÊN BẢN NGHIỆM THU VÀ THANH LÝ HỢP ĐỒNG" contains "bien ban" too,
# but should resolve to the more specific label).
_PAGE_KEYWORDS: list[tuple[str, str, str]] = [
    ("hop dong dich vu", "contract", "Hợp đồng dịch vụ"),
    ("thanh ly hop dong", "bbnt", "Biên bản thanh lý hợp đồng"),
    ("nghiem thu", "bbnt", "Biên bản nghiệm thu"),
    ("bien ban", "bbnt", "Biên bản nghiệm thu"),
    ("ban cam ket", "commitment", "Bản cam kết"),
    ("cam ket", "commitment", "Bản cam kết"),
    ("phu luc", "pit", "Phụ lục"),
    ("bang thong tin tra cuu", "pit", "Tra cứu thuế"),
    ("nguoi nop thue tncn", "pit", "Tra cứu thuế"),
    ("tra cuu", "pit", "Tra cứu thuế"),
    ("can cuoc cong dan", "id_front", "CCCD"),
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
    """
    lines = text.splitlines() or [text]
    top_n = max(1, len(lines) // 3)
    for line_group in (lines[:top_n], lines):
        candidates = [_flatten(norm(c)) for c in _title_candidates(line_group)]
        for kw, kind, label in _PAGE_KEYWORDS:
            if any(kw in c for c in candidates):
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
        "key": "hoten", "label": "Họ tên", "group": "Danh tính", "kind": "name",
        "anchors": ["ben cung ung dich vu", "ten nguoi nop thue"],
        "patterns": [], "roster_key": "name",
    },
    {
        "key": "cccd", "label": "Số CCCD", "group": "Danh tính", "kind": "text",
        "anchors": ["can cuoc", "so cccd", "msttncn"],
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


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    """Collapse sources that share the same (docId, value) to the
    highest-confidence one, preserving first-seen order.

    Multiple lines of the SAME document confirming the same value (e.g. a
    "Căn cước" line and an "MSTTNCN" line both showing the same digits) are
    one document's worth of evidence, not two -- without this, the reviewer
    would show duplicate same-doc chips for a value that appears on several
    lines of one document (see docs/test-findings.md #003).
    """
    best: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for s in sources:
        key = (s["docId"], s["value"])
        prev = best.get(key)
        if prev is None:
            order.append(key)
            best[key] = s
        elif s["confidence"] > prev["confidence"]:
            best[key] = s
    return [best[k] for k in order]


def extract_fields(words_by_doc: dict[str, dict[int, list[dict]]], roster_row: dict[str, str]) -> list[dict]:
    """Run every FIELD_SPECS entry over every doc/page's OCR words.

    `words_by_doc` is `{docId: {page_index: [scaled Word, ...]}}`. `expected`
    comes from `roster_row[roster_key]`; a field with no OCR hit anywhere
    still appears, with a single empty/zero-confidence source, so it reads
    as an exception to check rather than silently disappearing.
    """
    fields = []
    for spec in FIELD_SPECS:
        sources = []
        for doc_id, pages in words_by_doc.items():
            for page_idx, words in pages.items():
                lines = group_lines(words)
                if spec["kind"] == "name":
                    hits = find_name(lines, spec["anchors"])
                else:
                    hits = []
                    for pattern in spec["patterns"]:
                        hits.extend(find_in_lines(lines, spec["anchors"], pattern))
                for hit in hits:
                    sources.append({
                        "docId": doc_id,
                        "page": page_idx,
                        "value": hit["value"],
                        "bbox": hit["bbox"],
                        "confidence": hit["confidence"],
                    })
        sources = _dedupe_sources(sources)
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
# I/O layer (Task A4) — PyMuPDF render + pytesseract OCR. Not unit-tested
# (needs a real PDF + Tesseract); verified by running on real packets (A5).
# ---------------------------------------------------------------------------

def render_pages(pdf_path: str, start: int, end: int, out_dir: str, display_dpi: int = 150) -> list[dict]:
    """Render packet pages [start,end] (inclusive, 0-based) to PNGs in out_dir.

    Returns `DocPage` dicts `{src, width, height}` in packet order; `src` is
    the absolute PNG path (offline use — a server would rewrite this to a URL).
    """
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    zoom = display_dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pages = []
    try:
        for rel_idx, page_num in enumerate(range(start, end + 1)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat)
            path = os.path.join(out_dir, f"pg{rel_idx}.png")
            pix.save(path)
            pages.append({"src": path, "width": pix.width, "height": pix.height})
    finally:
        doc.close()
    return pages


def ocr_words(
    pdf_path: str, page_index: int, ocr_dpi: int = 300, display_dpi: int = 150,
) -> tuple[list[dict], float]:
    """OCR one page (0-based, absolute index) at `ocr_dpi` with Tesseract `vie`.

    Returns (words in OCR-pixel space, `display_dpi/ocr_dpi` scale factor) —
    the caller scales the words to display space with `scale_words`.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        zoom = ocr_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
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
    """
    os.makedirs(out_dir, exist_ok=True)
    pages = render_pages(pdf_path, start, end, out_dir, display_dpi=display_dpi)

    words_by_page: dict[int, list[dict]] = {}
    for rel_idx, abs_page in enumerate(range(start, end + 1)):
        words, factor = ocr_words(pdf_path, abs_page, ocr_dpi=ocr_dpi, display_dpi=display_dpi)
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
