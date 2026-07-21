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

import re
import unicodedata


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
