# Reviewer UI refinements — line-by-line pass (batch 1)

**Context:** refinements to the v2 checklist reviewer, gathered by walking the
checklist line-by-line with the Acc reviewer against the real case
(`FA-PM260226080`, 32 packets). Implement these as one batch in a separate session.
The C1/D1 (content-consistency) design is a separate, harder piece — **not** in this
batch (see the bottom of this file).

**Architecture recap (where things live):**
- Backend checklist builder: [`server/checklist.py`](../server/checklist.py) — `build_checklist(fields, match, docs)`; `_doc_by_kind`, the `_VALUE`/gate/confirm code tables.
- Page classifier / OCR: [`server/ocr_extract.py`](../server/ocr_extract.py) — `_PAGE_KEYWORDS`, `_FULL_PAGE_MARKERS`, `classify_page`, `segment_docs`, `locate_field`, `find_name`, `extract_fields`, `_geometric_value_slot`/`_label_region_bbox`.
- Pipeline: [`server/pipeline.py`](../server/pipeline.py) — `run_pipeline` writes `manifest.checks`.
- Reviewer shell + hotkeys + focus: [`src/components/FolderReview.tsx`](../src/components/FolderReview.tsx).
- Scan pane (pager, zoom, tabs, roster callout): [`src/components/EvidenceViewer.tsx`](../src/components/EvidenceViewer.tsx).
- Checklist panel: [`src/components/ChecklistPanel.tsx`](../src/components/ChecklistPanel.tsx).
- Types: [`src/ctv/types.ts`](../src/ctv/types.ts) (`CheckItem`, `EvidenceDoc`).

**Constraints (do not break):**
- OCR/data are **local, PII-bearing** — never commit real PDFs/PNGs/manifests/reports/PII.
- After changes: `npx tsc --noEmit`, `npx vitest run`, `pytest` (server) must all pass; then rebuild the offline export (`npm run build:single` → refresh `~/Downloads/Reviewer-v2.0.html`).
- Vietnamese UI throughout.

---

## Features

### 1. Doc viewer — view modes
Add a toolbar control to the scan pane with three modes:
- **1 trang** — single page (current behaviour), the only mode that auto-focuses (zoom-to-region).
- **Cuộn liên tục** — all pages of the current doc stacked, natural vertical scroll. (Bigger lift: today's zoom is a single-page CSS transform; continuous needs a scroll-stack layout with a width-based zoom.)
- **2 trang** — two-page spread, side by side; pager steps by 2.

Zoom/pan available in all modes. No new hotkey (toolbar only).

### 2. View mode follows the check
On selecting a check, open it in the view that fits it; a manual override holds while the reviewer stays on that check, and moving to another check re-applies that check's default. Three shapes:
- **value** → `1 trang`, auto-zoom to the detected bbox.
- **signature** (B3, C2) → `1 trang`, auto-zoom to the **last page, bottom** region (see #7).
- **skim** (G-DOC, D3, D1) → `Cuộn liên tục`, no zoom.

### 3. G-DOC "Đủ chứng từ bắt buộc"
Glance item — keep no-auto-focus. Opens in continuous view (via #2). No other change.

### 4. Remove the G-ID gate
Drop `G-ID` from the gate tier entirely. Identity is verified in detail by **B1** (name) + **A1** (CCCD); the always-on **header match badge** + CCCD-mismatch strip (MatchKeyStrip, driven by `matchedBy`/identities) keeps the automatic weak-match warning. Gates become 4: G-DOC, D3, B3, C2. `build_checklist` stops emitting G-ID; MatchKeyStrip is unaffected.

### 5. D3 / D1 conditional on the cam-kết doc
`D3` and `D1` route to the `commitment` ("Bản cam kết") doc, which is present in only ~8/32 packets (verified genuinely absent in the rest — not an OCR miss). **Only emit D3/D1 when the packet actually has a commitment doc.** General rule: **document-routed checks must not render when their evidence doc is missing** (no dead rows that open nothing). Applies to any Phụ lục-routed check too.

### 6. D3 "Xem mẫu" reference template
Add an optional `referenceAsset?: string` to `CheckItem`. When set, the check shows a **"Xem mẫu chuẩn — {year}"** button that opens the asset in a **lightbox/modal** over the scan pane (submitted doc stays underneath). For D3, the asset is the **blank current-year Mẫu 08/CK-TNCN** (Acc will provide) — PII-free, bundled as a static asset so it works in the offline export. No new review state. Button pattern is reusable for other checks later.

### 7. B3 & C2 signature focus (heuristic, not detection)
No signature detection (per "locate & look"). Instead, both signature gates auto-navigate to the evidence doc's **last page** and zoom to the **bottom band** (where sign/seal sit). `build_checklist` can compute "last page index of this doc" from `docs` + attach a bottom-band focus region.
- **No hard red highlight box** — a precise box implies detection we don't have. Land + zoom, with a soft caption ("Khu vực chữ ký & con dấu").
- The BBNT doc's last page is genuinely the signature page (the Phụ lục is segmented into its own doc).
- **C2 giáp lai**: support flipping to continuous view for the page-seam pass.
- When a packet has **two** BBNTs (nghiệm thu + thanh lý), C2 focuses the **thanh lý** one; both reachable via tabs.

---

## Bugs

### 8. Page counter not reset/clamped on doc switch ("4 / 2")
In `FolderReview`, `focusCheck` only resets `activePage` for value checks, and the tab-click handler (`onSelectDoc`) never resets it — so switching to a doc with fewer pages leaves a stale page index, showing e.g. "4 / 2" while falling back to page 0. **Fix:** reset `activePage` whenever the active doc changes (to the intended page per #2/#7, else 0) and clamp to `[0, pageCount-1]`.

### 9. Name (B1) lands on the BBNT instead of the contract
`hoten` uses name-detection, which only matched the **typed BBNT** (contract name is handwritten → no hit), so B1's source → BBNT while A1/A2/etc. correctly land on the contract's label-anchored value slot (conf 0.0, value unread, but boxed). **Fix:** make the name behave like the other value fields — anchor the contract's supplier-party label ("BÊN CUNG ỨNG DỊCH VỤ") and box the value slot **on the contract**, even when the handwriting is unread. Roster callout drives the comparison; the typed BBNT name stays reachable via its tab as a cross-check.
- Underlying principle (already reflected in the icon-only status): OCR **locates** the slot but usually **can't read** handwritten contract values — the human reads and compares; no auto-match on handwriting.

### 10. ←→ arrows are a dead no-op
In `FolderReview`'s keydown handler, the ArrowLeft/ArrowRight branch computes `n = source ? 1 : 0` and returns on `n < 2` — always true, so it never navigates (and never `preventDefault`s), yet the legend advertises "←→ tài liệu". **Fix:** bind ←→ to **page navigation**, rolling into the adjacent document at the first/last page. In `Cuộn liên tục` mode (pages already scroll), ←→ jumps between documents. Update the hotkey legend to "←→ trang".

---

## Not in this batch — C1 / D1 (content consistency)
`C1` (Nội dung & thời gian khớp BBNT) and `D1` (Thông tin & MST khớp cam kết) are
content/consistency checks (the deferred "Mode B" territory, possibly LLM-assisted on
GreenNode). Being designed separately; do **not** implement here.
