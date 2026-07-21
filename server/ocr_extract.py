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

import json
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


def find_name(lines: list[list[dict]], anchors: list[str], allow_next_line: bool = True) -> list[dict]:
    """Name fields aren't a regex pattern: the value is whatever text follows
    the anchor phrase (e.g. "Bên cung ứng dịch vụ") on the same line, or the
    whole next line if nothing follows there.

    Each anchor is a normalized, space-separated phrase (e.g. "ben cung ung
    dich vu"); it's matched as a contiguous run of words whose normalized
    text equals the anchor's tokens exactly (so "value" words can be told
    apart from "anchor" words on the same line).
    """
    hits = []
    tokenized = [a.split() for a in anchors]
    for idx, line in enumerate(lines):
        words_norm = [norm(w["text"]) for w in line]
        matched_end = None
        for tokens in tokenized:
            n = len(tokens)
            for i in range(len(words_norm) - n + 1):
                if words_norm[i:i + n] == tokens:
                    matched_end = i + n
                    break
            if matched_end is not None:
                break
        if matched_end is None:
            continue
        value_words = line[matched_end:]
        if not value_words and allow_next_line and idx + 1 < len(lines):
            value_words = lines[idx + 1]
        if not value_words:
            continue
        value = " ".join(w["text"] for w in value_words)
        hits.append({
            "value": value,
            "bbox": union_bbox(value_words),
            "confidence": min(w["conf"] for w in value_words) / 100,
        })
    return hits


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
        "key": "mst", "label": "Mã số thuế", "group": "Danh tính", "kind": "text",
        "anchors": ["ma so thue", "mst"],
        "patterns": [PATTERNS["MST"]], "roster_key": "mst",
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


def ocr_packet(
    pdf_path: str,
    start: int,
    end: int,
    roster_row: dict[str, str],
    out_dir: str,
    name: str,
    product: str,
    display_dpi: int = 150,
    ocr_dpi: int = 300,
) -> dict:
    """Render + OCR + extract one packet's page range into a CtvFolder manifest.

    Writes `manifest.json` (and the page PNGs from render_pages) into
    `out_dir`, and returns the manifest dict. Pages are addressed by index
    relative to the packet's own start (0-based), matching `docs[].pages[]`.
    """
    os.makedirs(out_dir, exist_ok=True)
    pages = render_pages(pdf_path, start, end, out_dir, display_dpi=display_dpi)

    words_by_page: dict[int, list[dict]] = {}
    for rel_idx, abs_page in enumerate(range(start, end + 1)):
        words, factor = ocr_words(pdf_path, abs_page, ocr_dpi=ocr_dpi, display_dpi=display_dpi)
        words_by_page[rel_idx] = scale_words(words, factor)

    fields = extract_fields({"packet": words_by_page}, roster_row)
    docs = [{"id": "packet", "kind": "contract", "label": "Hồ sơ", "pages": pages}]
    manifest = build_manifest(_slug(name), name, product, docs, fields)

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest
