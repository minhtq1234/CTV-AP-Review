# Stage C — Frontend upload flow — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development for the pure TS helpers; UI is verified in the browser preview (project convention: vitest for pure logic only). Steps use checkbox (`- [ ]`) syntax.

**Goal:** An in-app "Tải hồ sơ" flow: upload the big PDF (+ optional roster) → watch real processing progress → see the split result (packet cards) → open a packet into the existing `FolderReview` for real field validation, all driven by the Stage B backend.

**Architecture:** A small API client (`src/upload/api.ts`) + a phase state machine (`UploadFlow.tsx`) rendering four sub-screens; the review phase reuses the existing `FolderReview`/`EvidenceViewer` unchanged (the packet manifest is a `CtvFolder`). Pure helpers (URL building, progress %, stage labels, manifest base-prepend) are vitest-tested; the flow is verified in the browser against the running backend.

**Tech Stack:** React 18 + TS + Vite; Vitest for pure logic. Backend at `http://127.0.0.1:8000` (Stage B).

---

## File Structure
- Create `src/upload/api.ts` — backend client + types + pure helpers.
- Create `src/upload/api.test.ts` — vitest for the pure helpers.
- Create `src/components/UploadFlow.tsx` — phase state machine (upload→processing→result→review).
- Create `src/components/UploadScreen.tsx`, `ProcessingScreen.tsx`, `SplitResultScreen.tsx`.
- Modify `src/components/App.tsx` — add a `'upload'` mode + "Tải hồ sơ" tab (make it the first tab; keep the others).
- Modify `src/styles.css` — styles for dropzone / progress / result cards (reuse existing card/banner idiom).

---

## Task C1: API client + pure helpers (`src/upload/api.ts`)

- [ ] **Step 1 — failing vitest** `src/upload/api.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { stageLabel, progressPct, withAbsolutePageSrc } from './api'

describe('upload api helpers', () => {
  it('maps stages to Vietnamese labels', () => {
    expect(stageLabel('splitting')).toMatch(/tách|phát hiện|đối chiếu/i)
    expect(stageLabel('ocr')).toMatch(/đọc|trích|OCR/i)
    expect(stageLabel('done')).toMatch(/hoàn tất|xong/i)
  })
  it('computes percent, clamped, 0 when total is 0', () => {
    expect(progressPct({ stage: 'ocr', done: 8, total: 32, detail: '' })).toBe(25)
    expect(progressPct({ stage: 'queued', done: 0, total: 0, detail: '' })).toBe(0)
    expect(progressPct({ stage: 'done', done: 32, total: 32, detail: '' })).toBe(100)
  })
  it('prepends the API base to every page src', () => {
    const m: any = { docs: [{ pages: [{ src: '/api/jobs/J/packets/0/page/pg0.png', width: 1, height: 1 }] }] }
    const out = withAbsolutePageSrc(m, 'http://127.0.0.1:8000')
    expect(out.docs[0].pages[0].src).toBe('http://127.0.0.1:8000/api/jobs/J/packets/0/page/pg0.png')
  })
})
```
- [ ] **Step 2** `npx vitest run src/upload/api.test.ts` → fail.
- [ ] **Step 3 — implement** `src/upload/api.ts`:
  - `export const API_BASE = 'http://127.0.0.1:8000'`
  - types: `Progress {stage,done,total,detail}`, `PacketSummary {index,name,pages:[number,number],n_pages,confidence,flags:string[],labels:string[]}`, `JobStatus {status:'queued'|'processing'|'done'|'error',progress:Progress,result?:{summary:any,packets:PacketSummary[]},error?:string}`.
  - `stageLabel(stage)` → `{queued:'Đang chờ…', splitting:'Tách trang & phát hiện bìa, đối chiếu bảng kê…', ocr:'Đọc dữ liệu từng hồ sơ (OCR)…', done:'Hoàn tất', error:'Lỗi'}[stage] ?? stage`.
  - `progressPct(p)` → `p.total ? Math.round(Math.min(1, p.done/p.total)*100) : (p.stage==='done'?100:0)`.
  - `withAbsolutePageSrc(manifest, base)` → deep-map docs[].pages[].src → `base + src` (only when src starts with '/').
  - `createJob(pdf: File, roster?: File)` → FormData POST `${API_BASE}/api/jobs`, return `{job_id}`.
  - `getJob(id)` → GET `${API_BASE}/api/jobs/${id}` → `JobStatus`.
  - `fetchPacketManifest(jobId, index)` → GET `${API_BASE}/api/jobs/${jobId}/packets/${index}/manifest.json` → `withAbsolutePageSrc(json, API_BASE)` as `CtvFolder` (import the type from `../ctv/types`).
- [ ] **Step 4** vitest → PASS.
- [ ] **Step 5** commit `feat(upload): backend API client + pure helpers`.

## Task C2: Sub-screens (upload, processing, result)

- [ ] **Step 1 — implement** (UI; no unit tests):
  - `UploadScreen.tsx` — props `{onStart:(pdf:File,roster?:File)=>void, busy:boolean}`. A labeled dropzone / `<input type=file accept="application/pdf">` (required) + optional roster `<input accept=".xlsx">`; shows chosen filenames; "Bắt đầu xử lý" button disabled until a PDF is chosen or while busy.
  - `ProcessingScreen.tsx` — props `{status:JobStatus}`. Shows `stageLabel(status.progress.stage)`, a progress bar at `progressPct(...)%`, and the live detail (e.g. "gói 8/32 · <tên>"). Spinner styling.
  - `SplitResultScreen.tsx` — props `{result, onOpen:(index:number)=>void, onReset:()=>void}`. A summary banner (found / roster / auto-merged, mirroring the Python report wording) + a grid of packet cards (name, `p{a}–{b} · n trang`, confidence dot green/amber, flags as chips). Card click → `onOpen(index)`. A "Tải hồ sơ khác" reset button.
- [ ] **Step 2** commit `feat(upload): upload / processing / split-result screens`.

## Task C3: Flow orchestrator + App wiring

- [ ] **Step 1 — implement** `UploadFlow.tsx`:
  - state: `phase:'upload'|'processing'|'result'|'review'`, `jobId`, `status:JobStatus|null`, `packetIndex:number|null`, `folder:CtvFolder|null`, `err:string|null`.
  - upload: `onStart` → `createJob` → set jobId, phase `processing`.
  - processing: `useEffect` polling `getJob(jobId)` every 800ms while phase==='processing'; on `done` → set status, phase `result`; on `error` → show err. Clear interval on cleanup.
  - result: render `SplitResultScreen`; `onOpen(i)` → `fetchPacketManifest(jobId,i)` → set folder, phase `review`.
  - review: render existing `FolderReview folder={folder}` (import from './FolderReview') + a "← Quay lại danh sách" button back to `result`. `onUpdate` may be a no-op local setState (approve/reject not persisted server-side in this slice).
  - Handle backend-down: if `createJob`/`getJob` throws, show a friendly "Không kết nối được máy chủ xử lý (chạy backend ở cổng 8000)" message.
- [ ] **Step 2 — wire App.tsx**: add `'upload'` to the `Mode` union; add a first mode-bar button "Tải hồ sơ"; when `mode==='upload'` render `<UploadFlow/>` (full-width, no case tabs). Keep the existing three modes intact. Make `'upload'` the default mode.
- [ ] **Step 3** `npx tsc -b` clean; `npx vitest run` all green.
- [ ] **Step 4** commit `feat(upload): flow orchestrator + App 'Tải hồ sơ' mode`.

## Task C4: Browser verification (against the running backend)
- [ ] Start backend: `cd server && python3 -m uvicorn app:app --host 127.0.0.1 --port 8000` (background).
- [ ] Start dev server (`npm run dev` via Bash background; note the port).
- [ ] In the browser preview: on "Tải hồ sơ", upload the real PDF + roster; confirm the processing screen shows real advancing progress; confirm the split-result shows 32 cards (1 amber auto-merged); open a packet; confirm `FolderReview` renders the real scanned pages with field verdicts and the loupe auto-focuses the real scan (CCCD/MST/DOB green, handwritten fee an exception). Screenshot the result screen + an open packet.
- [ ] Report findings; note this flow needs the backend running. (Uploading the real PDF is fine locally; no PII committed.)

## Self-Review Notes
- Spec coverage: upload (C2), real progress (C2/C3 polling), split-result (C2), open packet → existing reviewer with real fields+loupe (C3 + reuse), backend-down handling (C3), App wiring/default (C3).
- Type consistency: `Progress`/`JobStatus`/`PacketSummary` match Stage B's `result`/`progress` shapes; `fetchPacketManifest` returns `CtvFolder` (from `src/ctv/types.ts`) with absolute page srcs; `FolderReview` consumes it unchanged.
- Placeholder scan: pure helpers TDD'd with concrete cases; screens/orchestrator specified with props + behavior; UI verified in-browser per project convention.
