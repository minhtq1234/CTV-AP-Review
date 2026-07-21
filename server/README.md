# server/ — OCR / extract → manifest (Stage A)

`ocr_extract.py` turns a source PDF's page range + a roster row into a
`CtvFolder` manifest — the exact JSON shape `src/ctv/types.ts` expects, so it
loads straight into the existing reviewer (`FolderReview`) with no new UI.

## Running the tests

```bash
cd server
python3 ocr_extract_test.py
```

Plain-`assert` tests, no framework. Expect `ALL OK`. Only the pure
geometry/text logic is unit-tested (word scaling, line grouping, bbox union,
diacritic-insensitive anchor matching, field assembly) — no PDF or Tesseract
needed for the test suite itself.

## Running the extractor offline (no server)

```python
from ocr_extract import ocr_packet

manifest = ocr_packet(
    pdf_path="/path/to/big-scan.pdf",
    start=192, end=199,              # 0-based, inclusive page range for one packet
    roster_row={                      # roster columns mapped to the 6 field keys
        "name": "...", "cccd": "...", "mst": "...",
        "tk": "...", "ngaysinh": "...", "phi": "...",
    },
    out_dir="/some/output/dir",       # writes manifest.json + pg0.png, pg1.png, ...
    name="...",
    product="...",
)
```

Requires: PyMuPDF (`fitz`), `pytesseract`, Pillow, and a local Tesseract
install with the `vie` language pack (`tesseract --list-langs` should list
`vie`).

## PII

The source PDF, roster spreadsheet, and every manifest/PNG this module
writes contain real personal data (names, CCCD, MST, bank accounts, dates of
birth). `ocr_extract.py` takes all real paths as caller-supplied arguments —
it never reads or writes anything outside `out_dir`. Never commit:

- the source PDF or roster spreadsheet,
- any `manifest.json` or page PNG produced by `render_pages`/`ocr_packet`,
- ad-hoc driver scripts that point at real files.

Only the module and its tests (synthetic data) belong in git. Run real
extractions with output directed at a scratch/temp directory outside the repo.
