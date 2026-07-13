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
