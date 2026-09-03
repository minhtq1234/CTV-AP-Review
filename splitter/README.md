# CTV folder splitter — deterministic slice

Turns one eForm submission (schedule Excel + CCCD photo Excel + scanned PDF) into
**one folder per collaborator**, each with a `manifest.json` in the same shape the
review app consumes. This slice does only the parts that need **no OCR**; the
OCR-dependent steps are emitted as explicit `needsOcr: true` stubs.

## Run

```bash
pip install openpyxl pymupdf          # deps
python3 split.py --out /tmp/split-out # manifests only (no media)
python3 split.py --out /tmp/split-out --extract-media   # + extract CCCD images (PII!)
python3 split.py --out /tmp/split-out --render-pdf       # + rasterize PDF pages (PII!)
```

Input paths are the three real files (see constants at the top of `split.py`).
**Do not commit the output** — it contains real PII. `splitter/output/` is gitignored;
prefer an out-of-repo `--out` dir.

## What it does (no OCR)

| Step | Status |
|---|---|
| Parse schedule Excel → 32 rows (authoritative claimed values) | real |
| Count embedded CCCD images | real |
| Read PDF page count | real |
| Segment PDF into per-CTV blocks | **stub** — order-based even split, `method: stub-order` |
| Link each CCCD image / PDF block to the right person | **stub** — needs CCCD OCR |
| Extract each field's value off the documents | **stub** — `sources: []`, needs OCR |
| Emit folder tree + manifests + `report.json` | real |

## The seam

The manifest is the contract between splitter and reviewer. Each field already
carries its `expected` (from Excel) and the `crossCheckDocs` it should be verified
against; the only gap is `sources` — which the real OCR/extraction pass fills. Once
filled, the folder drops straight into the review app with no other change.

## Real run output (Feb-2026 batch)

32 folders · STT 1–33 (missing 17, caught) · 61 CCCD images (~30 pairs) ·
262 PDF pages (front-matter 1–5, ~8 pp/CTV).

## Packet detector (scanned PDFs) — `detect_packets.py`

Splits a scanned multi-CTV PDF into per-collaborator packets by auto-detecting
the recurring contract-cover page, reconciles the count/order against the roster
spreadsheet, and writes a self-contained HTML report to eyeball the cuts.
No OCR, no GPU. Nothing is keyed to a specific page/packet count — the cover
template, threshold, and preamble length are derived from the file.

A roster-guided auto-prune step collapses mid-packet false-positive covers
(e.g. a "BIÊN BẢN NGHIỆM THU" cover that visually mimics the real contract
cover) into the packet they belong to, tagging the merge `auto-merged` (amber)
for a human to confirm rather than silently trusting it.

Run (report only):

    python3 detect_packets.py \
      --pdf "/path/to/submission.pdf" \
      --roster "/path/to/BẢNG KÊ ... .xlsx" \
      --out "/path/to/scratch/split-report.html"

Run (also export one PDF per packet — the core deliverable, turning the one
big scan into per-CTV files). `--out` and `--split-dir` are independent;
pass either or both:

    python3 detect_packets.py \
      --pdf "/path/to/submission.pdf" \
      --roster "/path/to/BẢNG KÊ ... .xlsx" \
      --out "/path/to/scratch/split-report.html" \
      --split-dir "/path/to/scratch/CTV-split"

Each packet is written as `NN_Tên-CTV_pA-B.pdf` (order, slugified name,
1-based inclusive page range), e.g. `01_Vũ-Thị-Kim-Ngân_p8-15.pdf`. A
missing/unmatched name becomes `CHUA-KHOP-TEN`; an auto-merged boundary gets
a `_can-xac-nhan` suffix so it stays visibly flagged for review even from
the filename alone, e.g. `24_Lưu-Ứng-Kỳ_p193-200_can-xac-nhan.pdf`.

Tests (pure logic, no PDF needed):

    python3 detect_packets_test.py

**PII:** the HTML report, its thumbnails, and the exported per-packet PDFs all
contain real personal data. Write them to a scratch location only —
`splitter/*.html` is gitignored, and `--split-dir`/`--out` should always point
outside the repo. Never commit a report or an exported PDF.
