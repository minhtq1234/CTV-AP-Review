# Upload → Split → OCR → Validate — design

**Date:** 2026-07-13
**Status:** approved (design); building in stages A → B → C

## Context

Prior slices built: the review app (synthetic data), and the **packet splitter**
(`splitter/detect_packets.py`) that turns one scanned multi-CTV PDF into per-CTV
packets + a report, reconciled against the Excel roster. This design closes the
full loop the user asked for:

> user uploads the big PDF → the app processes it → the user validates on the
> separated docs.

Decided with the user: **real local backend** (not simulated), and OCR runs
**locally** (data is PII) using **Tesseract + `vie`** (word-level bboxes for the
auto-focus loupe; PaddleOCR-vi is a later swap if accuracy is insufficient).

**Feasibility spike (done, on the real file):** Tesseract+`vie` reliably reads
the **typed** fields — biên-bản page produced VNG MST `0303490096`, the 12-digit
CCCD, and the bank account; tax-lookup produced MST + CCCD. Confirmed learnings:
cam-kết MST is in **spaced boxes** (needs a digits-with-gaps pattern), and
**handwritten** contract fields OCR poorly (→ low-confidence, which is the point).

## Goal

Upload the big scanned PDF in the app; a local backend splits it into per-CTV
packets, OCRs each packet to extract key field values (with bounding boxes),
and returns per-packet `CtvFolder` manifests; the user reviews the split, then
opens a packet into the **existing reviewer** for real field-level validation
(expected-from-roster vs OCR'd-from-document, with the auto-focus loupe).

## Non-goals

- Not a hosted/multi-user service — binds `127.0.0.1`, single local user.
- Not high-accuracy OCR — noisy/handwritten fields surface as low-conf/mismatch
  for the human; that is the intended division of labour, not a bug.
- No new reviewer UI — OCR output reuses the existing `CtvFolder`/`FolderReview`.
- Not part of the offline single-file export (that stays static/synthetic).

## The key architectural lever

The OCR stage emits, per packet, a **`CtvFolder` JSON in the exact shape the app
already loads** (`loadManifestFolder` → `FolderReview`). So field-level
validation on real data needs **no new review UI**: docs point at backend-served
page PNGs; each field carries `expected` (roster) + `sources` (OCR hits with
bbox + confidence); the existing verdict engine + loupe do the rest.

## Architecture (two processes over localhost)

```
Browser app (Vite :5173)  ──HTTP──▶  FastAPI backend (:8000, 127.0.0.1)
  upload PDF (+roster)                 ├─ splitter/detect_packets  (split)
  poll job progress                    ├─ server/ocr_extract       (OCR→fields)
  render split-result                  ├─ writes per-packet manifests + page PNGs
  open packet → reviewer   ◀───────────┘  serves manifests, pages, packet PDFs
```

## Stage A — OCR / extract → manifest (core new logic)

New module `server/ocr_extract.py`, usable offline (no server needed) so it can
be verified in the existing app immediately.

**Input:** the source PDF, a packet's page range, the packet's roster row.
**Output:** a `CtvFolder` dict (writeable as `manifest.json`).

Steps per packet:
1. **Render display pages** at a fixed DPI (e.g. 150) → PNGs; record each page's
   natural `width`/`height`. These become the manifest `docs[].pages[]`.
2. **OCR** each page at a higher DPI (e.g. 300) with `pytesseract.image_to_data`
   (lang=`vie`) → words with bbox + confidence, in OCR-pixel space.
3. **Scale** OCR bboxes to display-image space (`display_dpi / ocr_dpi`), so
   field bboxes match the manifest page dimensions (loupe alignment).
4. **Extract target fields** (pure, testable) via anchor + pattern over the OCR
   word stream, taking the bbox as the union of the matched words:
   - **CCCD** — 12 digits (also digits-with-gaps for boxed forms) near
     "Căn cước"/"MSTTNCN".
   - **MST** — 10–13 digits near "Mã số thuế"/"MST" (individual MST often == CCCD).
   - **Số TK** — digit run near "TK số"/"Số tài khoản".
   - **Ngày sinh** — date near "Ngày sinh".
   - **Phí dịch vụ** — money (thousands-separated) near "Phí dịch vụ".
   - **Họ tên** — text after "Bên cung ứng dịch vụ" / tax-lookup "Tên người nộp thuế".
5. **Build `CtvField`s:** `expected` = the roster value for that field; `sources`
   = every doc/page the value was OCR-found (value + scaled bbox + confidence).
   A field found on multiple pages yields multiple sources (worst-wins already
   supported). Missing → a source with empty value + low confidence so it reads
   as an exception to check.
6. Assemble the `CtvFolder` (docs + fields + name + product) and return it.

**Pure vs I/O split:** the extraction/pattern/scaling logic is pure (unit-tested
on synthetic OCR word lists); rendering + pytesseract calls are I/O (verified on
the real file). Expected values come from a `roster_row -> {field: value}` map
(reuse/extend the roster reader).

**Stage-A verification:** run offline on 2–3 real packets → write manifests +
page PNGs to the scratchpad → point the existing app's manifest loader at one →
confirm real fields render with correct verdicts and the loupe jumps to the
right spot on the real scan. (PII stays in scratchpad.)

## Stage B — FastAPI backend (`server/`)

- `POST /api/jobs` (multipart: `pdf` required, `roster` optional) → save to a
  temp job dir, start a background worker, return `{job_id}`.
- Worker pipeline with progress updates: **split** (detect_packets) →
  **OCR/extract** per packet (Stage A) → write manifests + page PNGs.
- `GET /api/jobs/{id}` → `{status, progress:{stage,pct,detail}, result?}` where
  `result` = summary + packet list (index, name, pages, confidence, flags,
  labels, `manifest_url`, `thumb_url`).
- `GET /api/jobs/{id}/packets/{i}/manifest.json`, `…/page/{p}.png`, `…/{i}.pdf`.
- Binds `127.0.0.1`; CORS allow-list the dev origin; job data under a temp dir,
  never committed. Run via `uvicorn`.

## Stage C — Frontend upload flow

New "Tải hồ sơ" entry alongside the existing modes:
1. **Upload** — dropzone for the PDF (+ optional roster) → `POST /api/jobs`.
2. **Processing** — polls `GET /api/jobs/{id}`; shows real staged progress with
   live counts (tách trang → phát hiện bìa → đối chiếu bảng kê → OCR n/N gói).
3. **Split result** — in-app report: summary banner + packet cards (green/amber),
   the auto-merged card flagged "cần xác nhận".
4. **Open packet** — fetch that packet's `manifest.json`, feed it to the existing
   `FolderReview` (docs load page PNGs from the backend) → real field validation.

`assetUrl()` already indirects image sources; backend page URLs pass through it
unchanged. The upload flow requires the backend running (documented).

## Data flow (per uploaded PDF)

```
PDF (+roster) → split → [packets] → per packet: render pages + OCR + extract
             → CtvFolder manifest (expected=roster, sources=OCR+bbox+conf)
             → app loads manifest → verdict engine + loupe → human validates
```

## Testing & verification

- **Stage A (unit):** field extraction on synthetic OCR word lists — CCCD (plain
  + spaced-boxes), MST, bank, date, money, name; bbox = union of matched words;
  scaling math; roster→expected mapping; multi-source assembly; missing→exception.
- **Stage A (e2e):** manifests for real packets open in the existing app with
  correct verdicts + loupe alignment (typed fields green, handwriting low-conf).
- **Stage B:** job lifecycle (POST → poll → done), endpoints return expected
  shapes; run the real PDF through and confirm 32 manifests + pages produced.
- **Stage C:** drive the browser flow end-to-end (upload → processing → result →
  open packet → fields visible), verified in the preview.

## Risks & mitigations

- **Handwriting/boxed-digit OCR noise** — expected; surfaces as low-conf/mismatch
  (the human's job). Mitigation: multi-source cross-check + roster as the clean
  expected value; loupe puts the reviewer on the exact spot fast.
- **Bbox misalignment** — OCR vs display DPI mismatch. Mitigation: single scale
  factor, unit-tested; e2e loupe check on real pages.
- **OCR latency** (300 dpi × 262 pages) — mitigation: OCR per packet in the
  worker with progress; only OCR pages likely to carry target fields if needed.
- **PII** — all uploads/outputs in a temp job dir on the machine; backend bound
  to localhost; nothing committed; code only.

## Success criterion

Upload the real 262-page PDF + roster in the app → watch real progress → get 32
packets (1 amber) → open a packet → see real field rows with expected(roster) vs
OCR(document) verdicts and the loupe auto-focusing the real scan. Typed fields
validate green; handwritten/boxed ones flag for the human. No PII committed.
