# Reviewer content checks + AI assist (batch 2)

**Context:** the content-consistency checks (C1, D1) and the AI-recap feature, from the
line-by-line design pass with the Acc reviewer. Separate, harder piece than
[batch 1](review-ui-refinements.md). Implement after / alongside batch 1.

**Positioning (important):** today's contracts/BBNTs are short and simple — Acc reads
them fast. So the AI here is **not** replacing the human on easy docs; it's a **preview
of where AI helps when docs get long/complex**. Frame it as assist, never verdict.

**Constraints:** OCR/data local + PII-bearing (never commit real docs/PII); Vietnamese UI;
GreenNode is VNG's own cloud (PII stays in-house) and only the **typed content region**
is ever sent; offline export must render with no network; tsc/vitest/pytest green + rebuild
`~/Downloads/Reviewer-v2.0.html` after.

---

## C1 — "Nội dung & thời gian khớp BBNT" (single check + AI recap)

- **One row, not split.** C1 stays a plain **confirm** check covering content *and* timing in one judgment; one flag (the note says which half is off, per note-and-resubmit). Selecting it opens the BBNT/Phụ lục; the reviewer confirms by eye (fast — docs are simple) and flags if off. **No side-by-side comparison view** (dropped — unnecessary for simple docs).
- Content lives in the **Phụ lục** (typed SOW/KPI/Actual) when present; falls back to the **BBNT body** when there's no Phụ lục.

### AI recap (the promise feature)

- **General "AI recap this doc" affordance** in the doc pane (a button), available on the **content-bearing docs** (contract, BBNT, Phụ lục, cam-kết) — not C1-only. C1 is just the natural first place a reviewer reaches for it.
- Opens a **popover** with:
  - **Tóm tắt** — 2–3 plain bullets of what the doc says / what was delivered + the period.
  - **Nhận định** — a tentative conclusion (e.g. "nội dung phù hợp phạm vi hợp đồng; thời gian khớp; không thấy mâu thuẫn"). A suggestion, **never** auto-marks or flags.
  - **Footer** — "Bản xem thử. AI hỗ trợ đọc nhanh hồ sơ dài/phức tạp — quyết định cuối cùng do bạn."
- **Generated on demand** (click → spinner → recap), then **cached** (repeat views instant).

### Two sources behind one popover
- **Live GreenNode** in the local/server app — server endpoint calls GreenNode with **only the typed content region**, returns `{ bullets, nhận định, disclaimer }`, cached (e.g. in the manifest/session). Needs GreenNode endpoint + creds (env). If not wired yet, the canned path still demos it; drop the live call in behind the same seam later.
- **Canned recap** baked into the synthetic demo packets → the **offline export** always shows the feature (no network, PII-free).

---

## D1 — "Thông tin & MST khớp cam kết"
**Status: parked** — proposal below, one open question before finalizing.

- **Conditional** — only on packets that have a cam-kết (batch-1 #5).
- **Purpose:** confirm the cam-kết (Mẫu 08) declarant *is this CTV* — if the name/MST on the commitment don't match, the PIT exemption doesn't apply to them.
- **Treat like a value check** (not a bare confirm): open the cam-kết, focus the **name + MST block** (anchor Mẫu 08's typed labels "Họ và tên" / "Mã số thuế"; value slot if handwritten), show the **roster callout** (expected name + MST); reviewer compares vs the bảng kê and flags. Same pattern as A1/A2/B1, on the cam-kết doc. (Effectively the same MST as A2, verified on the cam-kết specifically.)
- AI-recap button available here too (bonus); D1's core is the factual name/MST match.
- **OPEN QUESTION (parked):** does "Thông tin" mean just **name + MST** (proposed scope), or the broader declarant block (address, ID number)? Confirm before building.
