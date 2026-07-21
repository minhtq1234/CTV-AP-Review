# server/ — OCR/extract (Stage A) + FastAPI backend (Stage B)

`ocr_extract.py` renders + OCRs a source PDF's page range, segments it into
its constituent documents (`classify_page`/`segment_docs` — Hợp đồng, Biên
bản nghiệm thu, Bản cam kết, Phụ lục, Tra cứu thuế, CCCD), and extracts each
field's sources per document, returning `{"folder": {docs, fields}, "identity":
{cccd, name}}`. The `folder` shape matches `src/ctv/types.ts`'s `CtvFolder`
(minus `expected`, which isn't known yet) so it loads straight into the
existing reviewer (`FolderReview`) with no new UI, once the caller fills it
in.

`pipeline.py` orchestrates the packet splitter (`splitter/detect_packets.py`)
and `ocr_extract.py` into one call: split the source PDF into per-CTV
packets, OCR/segment each packet, then align it to its roster row by OCR'd
identity — `match_roster`: exact CCCD match, falling back to name — rather
than by packet position (a single swap or boundary shift used to mispair a
packet and cascade to the rest). The matched row fills each field's
`expected` (`fill_expected`) and the folder's name/product before the
manifest is written; an unmatched packet is flagged `"roster-unmatched"`
instead of being silently paired to the wrong row. `jobs.py` runs that
pipeline on a background thread with progress; `app.py` is the FastAPI
service that exposes it over HTTP (upload, poll, serve manifests + page
PNGs) for the frontend's upload flow.

## Running the tests

```bash
cd server
python3 ocr_extract_test.py     # plain-assert, no framework
python3 pipeline_test.py        # plain-assert, no framework (match_roster, roster indexing)
python3 jobs_test.py            # plain-assert, no framework
python3 app_test.py             # the pytest-free subset (rewrite, validation, traversal)
python3 -m pytest app_test.py -q   # full suite, incl. the two monkeypatch tests
```

Only pure logic is unit-tested this way (word scaling/line grouping/bbox
union/anchor matching/page classification in `ocr_extract`; roster indexing
and identity matching in `pipeline`; job lifecycle in `jobs`; URL
rewriting/validation/routing in `app`, with the real pipeline monkeypatched
out). `ocr_packet`/`run_pipeline`'s I/O layer (PyMuPDF render + pytesseract
OCR) has no unit test — it wires together already-tested pure logic around
real PDF/OCR I/O, and is verified by running the real file through the
server (below).

## Running the server

```bash
cd server
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Binds `127.0.0.1` only — this is a local, single-user tool, not a hosted
service. CORS allows the Vite dev origins (`localhost`/`127.0.0.1`, ports
5173-5175).

### Endpoints

- `POST /api/jobs` — multipart `pdf` (required) + `roster` (optional
  `.xlsx`). Saves both into a fresh `tempfile.mkdtemp()` job directory,
  starts the pipeline on a background thread, returns `{"job_id": "..."}`.
- `GET /api/jobs/{id}` — `{id, status, progress, result, error}`.
  `status` is `queued` / `processing` / `done` / `error`; `progress` is
  `{stage, done, total, detail}` (`stage` goes `"splitting"` -> `"ocr"`,
  with `done`/`total` counting packets OCR'd and `detail` the current
  packet's name); `result` (once `done`) is
  `{"summary": {found, roster_n, matched, auto_merged}, "packets": [...]}`.
- `GET /api/jobs/{id}/packets/{i}/manifest.json` — that packet's
  `CtvFolder` manifest, with every page's `src` rewritten from the on-disk
  path to `/api/jobs/{id}/packets/{i}/page/{basename}`.
- `GET /api/jobs/{id}/packets/{i}/page/{name}` — the rendered page PNG.
  `name` must match `^[A-Za-z0-9_.-]+\.png$` (400 otherwise) — a guard
  against path traversal, since it's joined onto a directory path.

### Example: upload the real file, poll, fetch a manifest

```bash
curl -s -F "pdf=@/path/to/scan.pdf" \
        -F "roster=@/path/to/roster.xlsx" \
        http://127.0.0.1:8000/api/jobs
# => {"job_id": "..."}

curl -s http://127.0.0.1:8000/api/jobs/<job_id>       # poll until status == "done"
curl -s http://127.0.0.1:8000/api/jobs/<job_id>/packets/0/manifest.json
```

## Roster -> field mapping, and packet alignment

`pipeline.all_roster_rows(rows)` maps every roster data row's Vietnamese
columns to the six field keys `ocr_extract.extract_fields` expects, plus a
product name:

| roster column          | field key  |
|-------------------------|------------|
| Họ và Tên               | `name`     |
| Số CCCD                 | `cccd`     |
| MST                     | `mst`      |
| Ngày Tháng Năm Sinh      | `ngaysinh` |
| Số TK                    | `tk`       |
| Phí dịch vụ              | `phi`      |
| Note (text before " - ") | product    |

`pipeline.build_roster_index(rows)` indexes all of them once, up front, by
`digits(cccd)` and by `norm(name)`. Each packet is then aligned to its row by
**identity**, not position: `match_roster(cccd, name, by_cccd, by_name)`
tries an exact CCCD match first, falls back to a name match (so a roster row
with a typo'd CCCD still aligns by name and correctly flags the CCCD field
as a mismatch, instead of not matching at all), and otherwise reports
`"unmatched"` — the packet gets flagged `"roster-unmatched"` rather than
silently paired to the wrong row. With no roster (`roster_path=None`), every
packet is `"unmatched"` — no expected values, no product.

## PII

The source PDF, roster spreadsheet, and every job directory (manifests,
page PNGs) this server reads or writes contain real personal data (names,
CCCD, MST, bank accounts, dates of birth). Job data always lives under a
per-job `tempfile.mkdtemp()` directory outside the repo — never commit:

- the source PDF or roster spreadsheet,
- any `manifest.json` or page PNG produced by a job or by
  `render_pages`/`ocr_packet` run offline,
- ad-hoc driver scripts that point at real files.

Only the server modules and their tests (synthetic/fake data) belong in
git. Before committing, `git status` should show none of the above.
