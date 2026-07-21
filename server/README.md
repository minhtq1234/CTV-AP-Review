# server/ — OCR/extract (Stage A) + FastAPI backend (Stage B)

`ocr_extract.py` turns a source PDF's page range + a roster row into a
`CtvFolder` manifest — the exact JSON shape `src/ctv/types.ts` expects, so it
loads straight into the existing reviewer (`FolderReview`) with no new UI.

`pipeline.py` orchestrates the packet splitter (`splitter/detect_packets.py`)
and `ocr_extract.py` into one call: split the source PDF into per-CTV
packets, then OCR/extract each into a manifest. `jobs.py` runs that pipeline
on a background thread with progress; `app.py` is the FastAPI service that
exposes it over HTTP (upload, poll, serve manifests + page PNGs) for the
frontend's upload flow.

## Running the tests

```bash
cd server
python3 ocr_extract_test.py     # plain-assert, no framework
python3 jobs_test.py            # plain-assert, no framework
python3 app_test.py             # the pytest-free subset (rewrite, validation, traversal)
python3 -m pytest app_test.py -q   # full suite, incl. the two monkeypatch tests
```

Only pure logic is unit-tested this way (word scaling/line grouping/bbox
union/anchor matching in `ocr_extract`; job lifecycle in `jobs`; URL
rewriting/validation/routing in `app`, with the real pipeline monkeypatched
out). `pipeline.py` itself has no unit test — it wires together
already-tested modules around real PDF/OCR I/O, and is verified by running
the real file through the server (below).

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

## Roster -> field mapping

`pipeline.roster_row_for(rows, packet_index)` maps the roster's Vietnamese
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

Packets align to roster rows strictly by order (packet *i* -> the *i*-th
roster data row), the same convention `detect_packets.reconcile` uses to
name packets. With no roster (`roster_path=None`), every packet gets an
empty `roster_row` — no expected values, no product.

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
