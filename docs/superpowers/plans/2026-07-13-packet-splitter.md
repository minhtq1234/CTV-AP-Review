# Packet Boundary Detector + Split Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split a scanned multi-CTV PDF into per-collaborator packets by auto-detecting the recurring contract-cover page, reconcile against the Excel roster, and emit a self-contained HTML split report to verify the cuts by eye.

**Architecture:** A pure-logic core (threshold derivation, cover→packet cutting, roster reconciliation, coarse page labels, report HTML) that is fully unit-tested with no PDF or image dependencies, wrapped by a thin I/O layer (PyMuPDF page rendering, numpy band similarity, PIL thumbnails, openpyxl roster read) that is verified by running on the real file. Nothing is keyed to the sample's page/packet counts — the cover template, threshold, and preamble length are all derived from the file.

**Tech Stack:** Python 3, PyMuPDF (fitz), NumPy, OpenCV (cv2) available but similarity done in NumPy, Pillow (PIL), openpyxl. Tests are plain-`assert` functions run with `python3` (no pytest dependency).

---

## File Structure

- **Create `splitter/detect_packets.py`** — the whole slice. Sections:
  - *Pure logic (unit-tested):*
    - `derive_threshold(scores) -> float` — midpoint of the largest gap in sorted scores.
    - `covers_from_scores(scores, threshold) -> list[int]` — page indices above threshold.
    - `packets_from_covers(cover_pages, total_pages) -> list[tuple[int,int]]` — inclusive (start,end) per packet; preamble before the first cover is dropped.
    - `@dataclass Packet` — one packet: `index,start,end,cover_score,name,flags,labels`; `n_pages`/`confidence` props.
    - `reconcile(bounds, page_scores, roster_names, threshold, len_range, near_margin) -> list[Packet]` — align packets to roster by order, attach confidence flags.
    - `extract_roster_names(rows, keywords) -> list[str]` — find the name column by header keyword, return names below it.
    - `coarse_label(aspect, ink, is_cover) -> str` — best-effort page type from cheap visual features.
    - `build_report_html(packets, roster_n, thumbs, title) -> str` — the report string.
  - *I/O layer (run-and-observe):*
    - `load_page_bands(pdf_path, dpi, band_frac, band_size) -> (bands, aspects, inks, n_pages)`.
    - `seed_scores(bands) -> (scores, seed_index)` — NumPy NCC; seed = most-recurrent band.
    - `render_thumb_datauri(pdf_path, page_index, width) -> str`.
    - `main(argv)` — compose, write report, print summary.
- **Create `splitter/detect_packets_test.py`** — plain-assert tests for every pure function; `__main__` runner prints `ALL OK`.
- **Modify `splitter/README.md`** — add a "Packet detector" section: how to run, PII note.
- **Modify `.gitignore`** — add `splitter/*.html` (reports carry PII; never commit).

**PII rule:** committed code takes all real paths as CLI args (no personal paths in source); the report + thumbnails are written to the scratchpad only and are gitignored.

---

## Task 1: Boundary core — threshold, covers, packets

**Files:**
- Create: `splitter/detect_packets.py`
- Create: `splitter/detect_packets_test.py`

- [ ] **Step 1: Write the failing test**

Create `splitter/detect_packets_test.py`:

```python
from detect_packets import derive_threshold, covers_from_scores, packets_from_covers

def test_derive_threshold_splits_bimodal():
    # covers ~0.9, rest ~0.2 -> threshold sits in the gap
    scores = [0.2, 0.18, 0.9, 0.22, 0.88, 0.19]
    t = derive_threshold(scores)
    assert 0.22 < t < 0.88, t

def test_covers_from_scores_selects_high():
    scores = [0.2, 0.9, 0.22, 0.88]
    assert covers_from_scores(scores, 0.5) == [1, 3]

def test_packets_drop_preamble_and_span_to_next_cover():
    # covers at pages 3 and 7, 10 pages total; pages 0-2 are preamble
    assert packets_from_covers([3, 7], 10) == [(3, 6), (7, 9)]

def test_packets_empty_when_no_covers():
    assert packets_from_covers([], 10) == []

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok {name}")
    print("ALL OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'detect_packets'` (or ImportError on the names).

- [ ] **Step 3: Write minimal implementation**

Create `splitter/detect_packets.py`:

```python
"""Split a scanned multi-CTV PDF into per-collaborator packets and report the cuts.

Boundaries are the recurring contract-cover pages, discovered from the file
(no hardcoded page numbers, threshold, or reference layout). Pure logic here is
unit-tested; the I/O layer below is verified by running on a real PDF.
"""
from __future__ import annotations


def derive_threshold(scores: list[float]) -> float:
    """Threshold = midpoint of the largest gap between consecutive sorted scores.

    Cover pages cluster high, everything else low; the biggest gap separates them.
    """
    s = sorted(scores)
    if len(s) < 2:
        return s[0] if s else 0.0
    best_gap, best_i = -1.0, 0
    for i in range(len(s) - 1):
        gap = s[i + 1] - s[i]
        if gap > best_gap:
            best_gap, best_i = gap, i
    return (s[best_i] + s[best_i + 1]) / 2


def covers_from_scores(scores: list[float], threshold: float) -> list[int]:
    """Page indices whose score exceeds the threshold (the recurring covers)."""
    return [i for i, sc in enumerate(scores) if sc > threshold]


def packets_from_covers(cover_pages: list[int], total_pages: int) -> list[tuple[int, int]]:
    """Inclusive (start, end) page range per packet.

    Preamble (pages before the first cover) is dropped. Each packet runs from its
    cover to the page before the next cover; the last runs to the final page.
    """
    if not cover_pages:
        return []
    cov = sorted(cover_pages)
    bounds = []
    for k, start in enumerate(cov):
        end = cov[k + 1] - 1 if k + 1 < len(cov) else total_pages - 1
        bounds.append((start, end))
    return bounds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: PASS — prints `ok test_covers...`, `ok test_derive...`, `ok test_packets...` lines then `ALL OK`.

- [ ] **Step 5: Commit**

```bash
git add splitter/detect_packets.py splitter/detect_packets_test.py
git commit -m "feat(splitter): boundary core — threshold, covers, packets"
```

---

## Task 2: Reconcile packets against the roster

**Files:**
- Modify: `splitter/detect_packets.py`
- Modify: `splitter/detect_packets_test.py`

- [ ] **Step 1: Write the failing test**

Add to `splitter/detect_packets_test.py` (below the imports, extend the import line):

```python
from detect_packets import reconcile, Packet

def _scores_for(bounds, cover=0.9):
    # build a per-page score list where each packet's start page scores `cover`
    n = max(e for _, e in bounds) + 1
    s = [0.1] * n
    for st, _ in bounds:
        s[st] = cover
    return s

def test_reconcile_aligns_names_in_order():
    bounds = [(3, 10), (11, 18)]
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An", "Binh"], threshold=0.5)
    assert [p.name for p in ps] == ["An", "Binh"]
    assert all(p.confidence == "green" for p in ps), [p.flags for p in ps]

def test_reconcile_flags_count_mismatch():
    bounds = [(3, 10), (11, 18)]
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An"], threshold=0.5)  # roster has 1, found 2
    assert ps[1].name is None
    assert "no-roster-match" in ps[1].flags
    assert all("count-mismatch" in p.flags for p in ps)

def test_reconcile_flags_length_out_of_range():
    bounds = [(3, 30)]  # 28 pages, way over the norm
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An"], threshold=0.5, len_range=(5, 12))
    assert "length-out-of-range" in ps[0].flags
    assert ps[0].confidence == "amber"

def test_reconcile_flags_near_threshold_cover():
    bounds = [(3, 10)]
    scores = _scores_for(bounds, cover=0.52)  # only just above threshold 0.5
    ps = reconcile(bounds, scores, ["An"], threshold=0.5, near_margin=0.05)
    assert "near-threshold" in ps[0].flags
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: FAIL — `ImportError: cannot import name 'reconcile'`.

- [ ] **Step 3: Write minimal implementation**

Add to `splitter/detect_packets.py` (top: add imports; then the class + function):

```python
from dataclasses import dataclass, field


@dataclass
class Packet:
    index: int              # 0-based packet number
    start: int              # 0-based first page (the cover)
    end: int                # 0-based last page, inclusive
    cover_score: float
    name: str | None = None
    flags: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)  # coarse type per page

    @property
    def n_pages(self) -> int:
        return self.end - self.start + 1

    @property
    def confidence(self) -> str:
        return "amber" if self.flags else "green"


def reconcile(
    bounds: list[tuple[int, int]],
    page_scores: list[float],
    roster_names: list[str] | None,
    threshold: float,
    len_range: tuple[int, int] = (5, 12),
    near_margin: float = 0.05,
) -> list[Packet]:
    """Build Packets, align to the roster by order, attach confidence flags."""
    packets: list[Packet] = []
    for i, (start, end) in enumerate(bounds):
        p = Packet(index=i, start=start, end=end, cover_score=page_scores[start])
        if roster_names is not None and i < len(roster_names):
            p.name = roster_names[i]
        if p.name is None:
            p.flags.append("no-roster-match")
        if not (len_range[0] <= p.n_pages <= len_range[1]):
            p.flags.append("length-out-of-range")
        if p.cover_score - threshold < near_margin:
            p.flags.append("near-threshold")
        packets.append(p)
    if roster_names is not None and len(bounds) != len(roster_names):
        for p in packets:
            p.flags.append("count-mismatch")
    return packets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: PASS — all `ok test_reconcile_*` lines then `ALL OK`.

- [ ] **Step 5: Commit**

```bash
git add splitter/detect_packets.py splitter/detect_packets_test.py
git commit -m "feat(splitter): reconcile packets to roster with confidence flags"
```

---

## Task 3: Extract roster names from spreadsheet rows

**Files:**
- Modify: `splitter/detect_packets.py`
- Modify: `splitter/detect_packets_test.py`

- [ ] **Step 1: Write the failing test**

Add to `splitter/detect_packets_test.py`:

```python
from detect_packets import extract_roster_names

def test_extract_roster_names_finds_column_below_header():
    rows = [
        ["BẢNG KÊ THANH TOÁN CTV", None, None],   # title band, skipped
        ["STT", "Họ và tên", "Số CCCD"],           # header row
        [1, "Nguyễn Văn A", "079..."],
        [2, "Trần Thị B", "052..."],
        [None, None, None],                         # trailing blank, skipped
    ]
    assert extract_roster_names(rows) == ["Nguyễn Văn A", "Trần Thị B"]

def test_extract_roster_names_empty_when_no_header():
    assert extract_roster_names([["x", "y"], [1, 2]]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: FAIL — `ImportError: cannot import name 'extract_roster_names'`.

- [ ] **Step 3: Write minimal implementation**

Add to `splitter/detect_packets.py`:

```python
def extract_roster_names(
    rows: list[list],
    keywords: tuple[str, ...] = ("họ và tên", "họ tên", "tên", "name"),
) -> list[str]:
    """Find the name column by header keyword; return non-empty names below it.

    Skips any title/blank rows above the table. Stops collecting at the first
    fully blank row after data has begun.
    """
    header_row = name_col = None
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell and any(k in str(cell).strip().casefold() for k in keywords):
                header_row, name_col = r, c
                break
        if header_row is not None:
            break
    if header_row is None:
        return []
    names: list[str] = []
    started = False
    for row in rows[header_row + 1:]:
        blank = all(cell is None or str(cell).strip() == "" for cell in row)
        if blank:
            if started:
                break
            continue
        started = True
        val = row[name_col] if name_col < len(row) else None
        if val and str(val).strip():
            names.append(str(val).strip())
    return names
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: PASS — `ok test_extract_roster_names_*` then `ALL OK`.

- [ ] **Step 5: Commit**

```bash
git add splitter/detect_packets.py splitter/detect_packets_test.py
git commit -m "feat(splitter): extract roster names from spreadsheet rows"
```

---

## Task 4: Coarse per-page label (best-effort)

**Files:**
- Modify: `splitter/detect_packets.py`
- Modify: `splitter/detect_packets_test.py`

- [ ] **Step 1: Write the failing test**

Add to `splitter/detect_packets_test.py`:

```python
from detect_packets import coarse_label

def test_coarse_label_cover_wins():
    assert coarse_label(aspect=0.71, ink=0.3, is_cover=True) == "Hợp đồng (bìa)"

def test_coarse_label_rotated_by_aspect():
    assert coarse_label(aspect=1.4, ink=0.2, is_cover=False) == "Phụ lục (xoay)"

def test_coarse_label_dense_vs_sparse():
    assert coarse_label(aspect=0.71, ink=0.25, is_cover=False) == "Văn bản"
    assert coarse_label(aspect=0.71, ink=0.04, is_cover=False) == "Biểu mẫu"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: FAIL — `ImportError: cannot import name 'coarse_label'`.

- [ ] **Step 3: Write minimal implementation**

Add to `splitter/detect_packets.py`:

```python
def coarse_label(aspect: float, ink: float, is_cover: bool) -> str:
    """Best-effort page type from cheap visual features.

    `aspect` is width/height (so a landscape/rotated page is > 1); `ink` is the
    fraction of dark pixels. Order matters: cover first, then rotated, then
    dense-text vs sparse-form.
    """
    if is_cover:
        return "Hợp đồng (bìa)"
    if aspect > 1.15:
        return "Phụ lục (xoay)"
    if ink >= 0.12:
        return "Văn bản"
    return "Biểu mẫu"
```

Note: `aspect` is passed as **width/height**, so a landscape/rotated page is `> 1`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add splitter/detect_packets.py splitter/detect_packets_test.py
git commit -m "feat(splitter): coarse per-page label from visual features"
```

---

## Task 5: Report HTML builder

**Files:**
- Modify: `splitter/detect_packets.py`
- Modify: `splitter/detect_packets_test.py`

- [ ] **Step 1: Write the failing test**

Add to `splitter/detect_packets_test.py`:

```python
from detect_packets import build_report_html

def test_report_html_has_summary_and_cards():
    ps = [Packet(index=0, start=7, end=14, cover_score=0.9, name="Nguyễn Văn A",
                 labels=["Hợp đồng (bìa)", "Văn bản"])]
    ps[0]  # green (no flags)
    html = build_report_html(ps, roster_n=1, thumbs={0: "data:image/png;base64,AAAA"},
                             title="Test")
    assert "<html" in html.lower()
    assert "Nguyễn Văn A" in html          # name rendered
    assert "p8–15" in html                 # 1-based inclusive range (7->8, 14->15)
    assert "1 / 1" in html                 # found / roster
    assert "data:image/png;base64,AAAA" in html  # thumbnail embedded

def test_report_html_marks_amber_and_mismatch():
    ps = [Packet(index=0, start=7, end=40, cover_score=0.9, flags=["length-out-of-range"])]
    html = build_report_html(ps, roster_n=2, thumbs={}, title="T")
    assert "amber" in html
    assert "length-out-of-range" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: FAIL — `ImportError: cannot import name 'build_report_html'`.

- [ ] **Step 3: Write minimal implementation**

Add to `splitter/detect_packets.py`:

```python
import html as _html


def build_report_html(
    packets: list[Packet],
    roster_n: int | None,
    thumbs: dict[int, str],
    title: str,
) -> str:
    """Self-contained HTML: summary banner + one card per packet."""
    amber = sum(1 for p in packets if p.confidence == "amber")
    roster_txt = "—" if roster_n is None else str(roster_n)
    aligned = "✓ khớp" if roster_n == len(packets) else "⚠ lệch số lượng"
    banner = (
        f'<div class="banner"><b>{_html.escape(title)}</b>'
        f'<span>{len(packets)} / {roster_txt} gói (tìm thấy / bảng kê) · {aligned}'
        f' · {amber} ranh giới cần xem lại</span></div>'
    )
    cards = []
    for p in packets:
        rng = f"p{p.start + 1}–{p.end + 1}"
        name = _html.escape(p.name) if p.name else "<i>chưa khớp tên</i>"
        thumb = thumbs.get(p.start) or thumbs.get(p.index) or ""
        img = f'<img src="{thumb}" alt="">' if thumb else '<div class="noimg">—</div>'
        chips = "".join(f'<span class="chip">{_html.escape(l)}</span>' for l in p.labels)
        flags = "".join(f'<span class="flag">{_html.escape(f)}</span>' for f in p.flags)
        cards.append(
            f'<div class="card {p.confidence}">{img}'
            f'<div class="meta"><div class="nm">{name}</div>'
            f'<div class="rng">{rng} · {p.n_pages} trang · score {p.cover_score:.2f}</div>'
            f'<div class="chips">{chips}</div><div class="flags">{flags}</div>'
            f'</div></div>'
        )
    style = (
        "body{font:14px system-ui;margin:24px;color:#1a1a1a}"
        ".banner{padding:12px 16px;background:#f4f6f8;border-radius:8px;margin-bottom:16px}"
        ".banner span{margin-left:12px;color:#555}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}"
        ".card{border:1px solid #e2e2e2;border-radius:8px;overflow:hidden;background:#fff}"
        ".card.green{border-left:4px solid #2e7d32}.card.amber{border-left:4px solid #e0a300}"
        ".card img{width:100%;height:150px;object-fit:cover;object-position:top;background:#fafafa}"
        ".noimg{height:150px;display:flex;align-items:center;justify-content:center;color:#bbb}"
        ".meta{padding:10px}.nm{font-weight:600}.rng{color:#666;font-size:12px;margin:4px 0}"
        ".chip{display:inline-block;font-size:11px;background:#eef;border-radius:10px;padding:1px 7px;margin:2px 2px 0 0}"
        ".flag{display:inline-block;font-size:11px;background:#fdeaea;color:#a11;border-radius:10px;padding:1px 7px;margin:4px 2px 0 0}"
    )
    return (
        f"<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title><style>{style}</style></head><body>"
        f"{banner}<div class='grid'>{''.join(cards)}</div></body></html>"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: PASS — all pure-logic tests green, `ALL OK`.

- [ ] **Step 5: Commit**

```bash
git add splitter/detect_packets.py splitter/detect_packets_test.py
git commit -m "feat(splitter): split-report HTML builder"
```

---

## Task 6: I/O layer — render bands, similarity/seed, thumbnails

**Files:**
- Modify: `splitter/detect_packets.py`

No unit test (image/PDF I/O); verified by the smoke run in Task 7.

- [ ] **Step 1: Add the I/O functions**

Add to `splitter/detect_packets.py`:

```python
import base64
import io

import fitz          # PyMuPDF
import numpy as np
from PIL import Image


def load_page_bands(
    pdf_path: str,
    dpi: int = 40,
    band_frac: float = 0.28,
    band_size: tuple[int, int] = (160, 64),
) -> tuple[list[np.ndarray], list[float], list[float], int]:
    """Render each page grayscale at low DPI; return the resized top band, the
    page aspect (width/height), and ink density (fraction of dark pixels) per page.
    """
    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    bands, aspects, inks = [], [], []
    bw, bh = band_size
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        aspects.append(pix.width / pix.height if pix.height else 1.0)
        arr = np.asarray(img)
        inks.append(float((arr < 128).mean()))
        top = img.crop((0, 0, img.width, max(1, int(img.height * band_frac))))
        top = top.resize((bw, bh))
        bands.append(np.asarray(top, dtype=np.float32))
    n = doc.page_count
    doc.close()
    return bands, aspects, inks, n


def _unit(band: np.ndarray) -> np.ndarray:
    v = band.ravel().astype(np.float32)
    v = v - v.mean()
    norm = np.linalg.norm(v)
    return v / norm if norm else v


def seed_scores(bands: list[np.ndarray]) -> tuple[list[float], int]:
    """NumPy normalized cross-correlation between all top-bands.

    Seed = the most-recurrent band (highest summed similarity to its nearest
    neighbours) — i.e. the cover, which repeats once per packet. Returns each
    page's similarity to the seed, and the seed index.
    """
    if not bands:
        return [], -1
    M = np.stack([_unit(b) for b in bands])   # (n, d), zero-mean unit rows
    sim = M @ M.T                              # (n, n) NCC in [-1, 1]
    np.fill_diagonal(sim, -1.0)                # ignore self-match
    k = max(3, len(bands) // 20)
    recurrence = np.sort(sim, axis=1)[:, -k:].sum(axis=1)
    seed = int(np.argmax(recurrence))
    return sim[seed].tolist(), seed


def render_thumb_datauri(pdf_path: str, page_index: int, width: int = 220) -> str:
    """Render one page to a small PNG data: URI (for the report)."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    zoom = width / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    png = pix.tobytes("png")
    doc.close()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `cd splitter && python3 -c "import detect_packets; print('import ok')"`
Expected: prints `import ok` (no syntax/import errors).

- [ ] **Step 3: Commit**

```bash
git add splitter/detect_packets.py
git commit -m "feat(splitter): I/O layer — page bands, NCC seed, thumbnails"
```

---

## Task 7: CLI `main` + smoke run on the real PDF

**Files:**
- Modify: `splitter/detect_packets.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add `.gitignore` entry**

Add this line to `.gitignore` (reports carry PII):

```
splitter/*.html
```

- [ ] **Step 2: Add `main` to `splitter/detect_packets.py`**

```python
import argparse
import sys

import openpyxl


def _roster_rows(xlsx_path: str) -> list[list]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    return [list(row) for row in ws.iter_rows(values_only=True)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect per-CTV packets in a scanned PDF.")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--roster", help="path to the roster .xlsx (optional)")
    ap.add_argument("--out", required=True, help="output HTML report path")
    ap.add_argument("--dpi", type=int, default=40)
    args = ap.parse_args(argv)

    bands, aspects, inks, n = load_page_bands(args.pdf, dpi=args.dpi)
    scores, seed = seed_scores(bands)
    threshold = derive_threshold(scores)
    cover_pages = covers_from_scores(scores, threshold)
    bounds = packets_from_covers(cover_pages, n)

    roster_names = None
    if args.roster:
        roster_names = extract_roster_names(_roster_rows(args.roster))

    packets = reconcile(bounds, scores, roster_names, threshold)
    cover_set = set(cover_pages)
    for p in packets:
        p.labels = [
            coarse_label(aspects[pg], inks[pg], is_cover=(pg in cover_set))
            for pg in range(p.start, p.end + 1)
        ]

    thumbs = {p.start: render_thumb_datauri(args.pdf, p.start) for p in packets}
    html = build_report_html(
        packets, roster_n=(len(roster_names) if roster_names is not None else None),
        thumbs=thumbs, title="Tách hồ sơ CTV — báo cáo ranh giới",
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"pages={n} seed_page={seed + 1} threshold={threshold:.3f} "
          f"covers={len(cover_pages)} roster={len(roster_names) if roster_names else '—'}")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the full pure-logic test suite once more**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: `ALL OK`.

- [ ] **Step 4: Smoke-run on the real PDF (writes report to scratchpad)**

Run (single line; SCRATCH is this session's scratchpad dir):
```bash
cd splitter && SCRATCH="/private/tmp/claude-501/-Users-lap16603-Desktop-ap-review-prototype--claude-worktrees-gracious-dijkstra-fbc604/c6f6feb3-944b-46ae-a2d6-b94a17594cd0/scratchpad" && python3 detect_packets.py --pdf "$HOME/Downloads/FA-PM260226080.pdf" --roster "$HOME/Downloads/Chi phí Cộng tác viên/BẢNG KÊ THANH TOÁN CTV -THÁNG 2.2026.xlsx" --out "$SCRATCH/split-report.html"
```
Expected: a summary line with `pages=262`, a `seed_page` inside the packet region, `covers=` roughly the roster size (~31–33), `roster=` ~33, and `report -> …/split-report.html`.

- [ ] **Step 5: Inspect the report to verify the cuts**

Open/read `$SCRATCH/split-report.html` (view in the browser pane or read the HTML). Confirm: the banner shows found ≈ roster and "✓ khớp"; cards show sensible page ranges (~8 pages each), cover thumbnails that are contract covers, and names aligned in roster order. Note any amber cards.

If covers ≠ roster or spacing looks wrong, tune in this order and re-run Step 4: (a) `--dpi` up to 50 for sharper bands; (b) `band_frac`/`band_size` defaults in `load_page_bands`; (c) the `k` neighbour count in `seed_scores`. Do not hardcode page numbers.

- [ ] **Step 6: Commit**

```bash
git add splitter/detect_packets.py .gitignore
git commit -m "feat(splitter): CLI main + gitignore reports"
```

---

## Task 8: README + final verification

**Files:**
- Modify: `splitter/README.md`

- [ ] **Step 1: Add a "Packet detector" section to `splitter/README.md`**

Append:

```markdown
## Packet detector (scanned PDFs) — `detect_packets.py`

Splits a scanned multi-CTV PDF into per-collaborator packets by auto-detecting
the recurring contract-cover page, reconciles the count/order against the roster
spreadsheet, and writes a self-contained HTML report to eyeball the cuts.
No OCR, no GPU. Nothing is keyed to a specific page/packet count — the cover
template, threshold, and preamble length are derived from the file.

Run:

    python3 detect_packets.py \
      --pdf "/path/to/submission.pdf" \
      --roster "/path/to/BẢNG KÊ ... .xlsx" \
      --out "/path/to/scratch/split-report.html"

Tests (pure logic, no PDF needed):

    python3 detect_packets_test.py

**PII:** the HTML report and its thumbnails contain real personal data. Write it
to a scratch location only — `splitter/*.html` is gitignored. Never commit a report.
```

- [ ] **Step 2: Run the test suite a final time**

Run: `cd splitter && python3 detect_packets_test.py`
Expected: `ALL OK`.

- [ ] **Step 3: Confirm no PII staged**

Run: `git status --porcelain && git ls-files splitter/ | grep -i '\.html$' || echo "no html tracked (good)"`
Expected: only `splitter/README.md` modified; `no html tracked (good)`.

- [ ] **Step 4: Commit**

```bash
git add splitter/README.md
git commit -m "docs(splitter): document packet detector + PII note"
```

---

## Self-Review Notes

- **Spec coverage:** Stage 1 auto-derive cover/threshold → Tasks 1, 6 (`derive_threshold`, `seed_scores`, `covers_from_scores`). Preamble derived → Task 1 (`packets_from_covers` drops pages before first cover). Stage 2 reconcile/guardrail → Task 2. Stage 3 coarse labels → Task 4. Stage 4 HTML report → Task 5. Roster read → Task 3 + Task 7. Generality (no hardcoded counts) → Tasks 1/6/7 derive everything; tuning note forbids hardcoding page numbers. PII handling → Task 7 gitignore + Task 8 note/check.
- **Placeholder scan:** none — every step has full code or an exact command.
- **Type consistency:** `Packet` fields (`index,start,end,cover_score,name,flags,labels`) and function names (`derive_threshold`, `covers_from_scores`, `packets_from_covers`, `reconcile`, `extract_roster_names`, `coarse_label`, `build_report_html`, `load_page_bands`, `seed_scores`, `render_thumb_datauri`, `main`) are used identically across tasks. `aspect` is width/height everywhere. Report uses `thumbs[p.start]`; `main` builds `thumbs` keyed by `p.start`.
```
