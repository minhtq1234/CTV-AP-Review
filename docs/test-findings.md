# Test findings / bug log

Running log of issues found while testing the upload → split → OCR → validate
flow on real submissions. Newest entries at the bottom. No PII in this file —
reference packets by STT / field, not by real values.

| ID | Area | Status | Summary |
|----|------|--------|---------|
| 001 | OCR / fields | resolved | MST/CCCD kept independent; MST reads MSTTNCN; now doc-labeled |
| 002 | alignment | resolved | Now align by OCR'd CCCD (name fallback), not position |
| 003 | doc segmentation | resolved | Packet split into per-document EvidenceDocs; sources doc-labeled |
| 004 | multi-doc sources | resolved | Field navigable on every doc incl. handwritten "cần xem"; value is a hint |
| 005 | locate region | resolved | "cần xem" region computed geometrically from the label's right edge; box on the value slot |
| 006 | doc-switch focus | resolved | Doc-tab switch re-focuses the selected field's source on the new document |
| 007 | orphaned processing case | resolved | Reconciled to "error" on CaseStore load; no more perpetual spinner |
| 008 | name not found on some docs | resolved | Added "Tên tôi là"/"Họ và tên" anchors + scoped "cần xem" fallback |
| 009 | inconsistent doc segmentation | resolved | Tra-cứu + cam-kết now detected anywhere on page; Phụ lục residual → #010 |
| 010 | rotated Phụ lục not segmented | open (low) | Rotated SOW appendix OCR-garbled → folds into "Biên bản" |

**Resolution (all three):** fixed together in commits `c84d52c`..`d03cdaf` (plan
`docs/superpowers/plans/2026-07-13-fix-segment-and-align.md`). Verified live on the
real file with the v3 error roster: the previously all-red packet at p154–161 now
correctly resolves to **Nguyễn Đào Hồng Hạnh** (name green), shows 3 document tabs
(Hợp đồng / Biên bản thanh lý / Tra cứu thuế), and each field's sources are labeled
by document. Nguyễn Thảo Ly ↔ Nguyễn Đào Hồng Hạnh (swapped between roster order and
PDF order) are now paired correctly by CCCD. Remaining amber/red on that packet are
legitimate OCR outcomes (handwritten contract fields → flagged for a human), not the
mispairing bug.

---

## 001 — MST and CCCD resolve to the same value

**Observed:** On a packet, the `Số CCCD` and `Mã số thuế` rows show the identical
number and both go green. The document prints the same value on both the
`CCCD số` line and the `MSTTNCN` line.

**Why it's flagged:** For this collaborator the two coincide, but MSTTNCN and
CCCD are **not** always equal — a legacy 10-digit individual MST differs from the
12-digit CCCD. So the tool must handle both cases.

**To do / decide:**
- Confirm the MST field always reads the **MSTTNCN line independently** and never
  falls back to echoing the CCCD value (verify on a packet where they differ).
- Decide the display when they're equal (two identical rows is redundant) vs when
  they differ.
- **Do NOT** add a hard "MSTTNCN == CCCD" rule — that would false-flag legitimate
  legacy MSTs.

**Status:** open — noted during testing; no fix applied yet.

---

## 002 — Packet matched to the wrong roster row (position-based alignment)

**Observed:** A packet was labeled with one collaborator's name (roster) while its
pages were entirely a **different** collaborator's documents; all 6 fields went red.

**Root cause:** Packets are paired to roster rows **by position** (i-th packet →
i-th roster row), which assumes the PDF packet order == roster row order. A single
swap or boundary shift mispairs a packet and cascades to the rest. The
"N/N đã khớp tên" banner only verifies the **count**, not per-packet correctness,
so it gives false confidence. Names are handwritten/OCR-unreliable, so the current
logic can't self-check the pairing.

**Fix direction:** Align each packet to its roster row by **matching the OCR'd
CCCD** (reliable, unique per person) instead of by position; fall back to
name/MST fuzzy match; flag packets whose CCCD matches no roster row (or matches
none confidently) rather than blindly assigning by order.

**Status:** open — high priority (produces wholesale false mismatches).

## 003 — Packet not segmented into its constituent documents

**Observed:** A packet is really ~4 documents (Hợp đồng, Biên bản nghiệm thu,
Phụ lục đánh giá, Tra cứu thuế), but the OCR pipeline bundles all pages into a
single `EvidenceDoc` labeled "Hồ sơ". Every field source chip therefore just says
"Hồ sơ" — you can't tell which document a value came from — and a field that
legitimately appears in several documents (e.g. CCCD on the contract + biên bản +
tax-lookup) shows duplicate same-value sources with no document distinction.

**Note (user):** "there are actually 4 documents; many data fields appear more
than 1 place." The multi-source cross-check is correct in spirit, but sources need
per-document labels and the packet needs doc-type segmentation — like the
synthetic folders' doc tabs (CCCD / Hợp đồng / Tờ khai PIT / Biên bản).

**Fix direction:** Segment packet pages into documents by detecting each doc's
cover/type; build one `EvidenceDoc` per document; label each field source with its
document so the reviewer shows "checked across N documents" meaningfully.

**Status:** open — enables both clearer sources and the CCCD-based alignment in 002.

## 004 — A field must be checkable on every document it appears on

**Observed:** `Ngày sinh` appears on both the Hợp đồng and the Biên bản (visible in
the viewer), but only the Biên bản shows as a source. The contract's copy is
**handwritten**, OCR couldn't read it, so no source was emitted — leaving no chip
to click to verify that occurrence. Same for CCCD/MST/TK across the 3 documents.

**Want (user):** check the data on all documents. Each field should be navigable
on **every document it appears on**, not only where OCR succeeded.

**Fix direction:** for each field, emit one source per document whose label is
present. Readable (typed) → value + bbox + confidence + verdict (as now).
Unreadable (handwritten) → a "cần xem" source pointing at the location (region
after the label) so the loupe still jumps there. Treat unread occurrences as
"chưa đọc được — cần kiểm tra" (navigable, flagged) rather than a hard mismatch,
so a field whose readable copies match isn't false-failed by an unread copy.
Requires: extraction change (server) + a source-level "unread" state in the
reviewer (checks/verdict + source-chip rendering).

**Guiding principle (user):** the key action is the reviewer validating **with
their own eyes**, not data extraction. Prioritize the **label/location** over the
**value** — reliably find where each field appears on each document and guide the
eye there; the OCR'd value and auto-verdict are hints, not the decision. Locating a
label is far more robust than reading handwriting, so this plays to the tool's
strength.

**Status:** resolved — commits `aa0e8fe` (server: locate each field on every doc,
read or "cần xem") + `8086aec` (reviewer: per-doc sources, value is a hint not the
gate). Verified live on the real file (Nguyễn Hoàng Phúc): Ngày sinh/CCCD/MST/TK
each show a source on both Hợp đồng and Biên bản; clicking the contract's
"cần xem" chip switches to that document and boxes the handwritten value for a human
read; unread copies don't turn matching fields red.

## 005 — "cần xem" located region lands on the wrong field slot

**Observed (packet 0, Huỳnh Thị Thúy Phượng, contract page 1241×1755):** the
unread (handwritten) located regions point at the wrong place:
- `cccd` → bbox `(x=682, y=720, w=24, h=31)` — a tiny box on the "30" of
  "Ngày cấp" (issue date), not the CCCD slot.
- `ngaysinh` → bbox `(x=418, y=656, w=524, h=30)` — 524px wide, spanning the DOB
  and "Quốc tịch".
(Read/typed sources on the biên bản are tight and correct — only the unread
located-region path is wrong.)

**Cause:** `locate_field`'s unread-region heuristic ("region after the label")
misfires on lines packing several labeled fields ("Căn cước số … Ngày cấp …
Nơi cấp"; "Ngày sinh … Quốc tịch") — sometimes latching a stray token, sometimes
running to end-of-line.

**Fix direction:** bound the located region to the span **from the end of the
field's own label to the start of the next label on that same line** (a word
matching a known anchor or ending in ":"); default to a reasonable width if the
field is last on the line. That boxes the value slot precisely — essential since
"look here" is the whole point.

**Status:** resolved — commit `910d888`. First pass (bound width to end-of-line)
looked fixed by the numbers but the live browser check showed the CCCD box still on
"Ngày cấp": when a handwritten value produces no OCR tokens, a token-based region
start latches the next field's label. Final fix computes the region **geometrically**
— from the label's right edge to the next label's left edge — so it covers the value
slot even with no value tokens. Verified by rendering the box onto the contract page:
CCCD box on the CCCD number, DOB box tight before "Quốc tịch".

## 006 — Switching document by tab drops the selected field's highlight

**Observed:** With a field selected, clicking a *document tab* (e.g. "Biên bản
thanh lý hợp đồng") shows the page but **no box** — even though that field has a
read source there. The box only appears when clicking the field's source *chip*.
(Confirmed the biên-bản bbox is correct: clicking Ngày sinh's biên-bản chip boxes
"22/05/1989".) Cause: `FolderReview`'s `onSelectDoc` sets `focusBbox = null`.

**Want:** when a field is selected, switching to a document where that field has a
source should **auto-focus that source's bbox** on the new document — so checking a
field across its documents is one click per doc and the eye is always guided.

**Fix direction:** in `FolderReview`, on document switch, if the selected field has
a source on the newly-active document, focus that source's bbox instead of clearing;
only clear when the field has no source there. Keeps free-browsing sensible while
serving the cross-document check.

**Status:** resolved — commit `4a7bc82`. `onSelectDoc` now re-focuses the selected
field's source on the newly-active document (via `focusAt`), clearing only when the
field has no source there. Verified live: with Ngày sinh selected, clicking the
"Biên bản thanh lý hợp đồng" tab boxes "22/05/1989" on the biên bản.

## 007 — Orphaned "processing" case after an interrupted pipeline

**Observed:** A case whose pipeline was killed mid-run (the case-management build
agent's B3 e2e hit the 600s watchdog during OCR) left `case.json` with
`status="processing"`, 0 packets, and no worker. On the next backend restart the
startup index rebuild loaded it as a perpetual "Đang xử lý…" case that never
completes. Deleted it manually via `DELETE /api/cases/{id}`.

**Fix direction (not urgent for a local prototype):** on startup index rebuild,
reconcile any case still in `status="processing"` (no live worker) to a stale/error
state (e.g. `status="error"`, message "xử lý bị gián đoạn"), so the list can offer
delete/retry instead of showing it processing forever.

**Status:** resolved — commit `ecf8c2d`. `CaseStore._load` reconciles any on-disk
case still `status="processing"` to `status="error"` ("Xử lý bị gián đoạn — vui lòng
xoá và tải lại."), leaving other statuses untouched. Verified live: created a case,
killed the backend mid-processing, restarted → the case shows "error", not a
perpetual spinner.

## 008 — Name field not detected on some documents

**Observed (Trần Ứng Hỷ):** `Họ tên` shows a source only on the Biên bản — not on
the Bản cam kết or the Hợp đồng dịch vụ.

**Cause:** the name field's anchors are only
`["ben cung ung dich vu", "ten nguoi nop thue"]` (ocr_extract.py FIELD_SPECS).
- **Bản cam kết** labels the name **"Tên tôi là:"** — not in the anchor list → missed.
- **Hợp đồng dịch vụ** matches the "BÊN CUNG ỨNG DỊCH VỤ" anchor, but the name there
  is **handwritten** → OCR can't read it and the name-shape guard drops it.
- The name field is deliberately stricter than others (labeled + name-shaped match,
  no "cần xem" fallback) because "Bên Cung Ứng Dịch Vụ" recurs in prose dozens of
  times; a raw locate-fallback would flood with false name sources.

**Fix direction:**
1. Add label variants to the name anchors — at least `"ten toi la"` (Bản cam kết)
   and `"ho va ten"` — so more documents' name occurrences are found.
2. Give the handwritten party-line name a **scoped** "cần xem" located source (only
   the actual signature/party line via the labeled + name-shape context, NOT every
   prose mention of the anchor phrase), so it's navigable even when unreadable —
   consistent with the locate-&-look principle (#004).

**Status:** resolved — commits `ac6e55c`, `22dbb3e`. Added `"ten toi la"`,
`"ho va ten"` (and `"en toi la"` for a real Tesseract dropped-leading-letter
artifact) to the name anchors, and gave the name a scoped "cần xem" located fallback
(labeled context only, no prose flood). Verified live on Trần Ứng Hỷ: Họ tên now has
sources on Hợp đồng (cần xem), Biên bản (read), and Bản cam kết (cần xem).

## 009 — Inconsistent document segmentation (docs fold into "Biên bản")

**Observed:** two 8-page packets with the same 4 underlying documents segment
differently — Trần Ứng Hỷ → 4 docs (Hợp đồng 4p / Biên bản 2p / Bản cam kết 1p /
Tra cứu thuế 1p); Huỳnh Thị Thúy Phượng → only 2 docs (Hợp đồng 4p / **Biên bản 4p**
with the cam kết + tra-cứu pages folded in, so the biên bản's "page 4/4" is actually
the tax-lookup).

**Cause:** `segment_docs`/`classify_page` starts a new document when it recognizes
that page's title/heading. When a heading isn't recognized — OCR noise on the title
band, or the tax-lookup page being a screenshot with a small/nonstandard header —
the page folds into the preceding document. (Known #003 limitation.)

**Impact:** cosmetic/navigational only — field extraction, matching, packet count,
and identity are unaffected (fields are found across all pages regardless of doc
grouping). Only the document TABS are inconsistent (count varies; a page can sit
under the wrong label).

**Fix direction:** strengthen per-doc-type title detection in `segment_docs` —
add tra-cứu headings ("bang thong tin tra cuu", "thong tin ve nguoi nop thue",
"gdt.gov.vn") and cam-kết headings ("ban cam ket", "08/ck-tncn"), tolerant of OCR
title-band noise; consider light layout cues for the screenshot-style tax page.

**Status:** resolved — commit `dd07c85`. `classify_page` gained a full-page marker
fallback for the two unambiguous doc types: tra-cứu ("bảng thông tin tra cứu",
"thông tin về người nộp thuế", "gdt.gov.vn", …) and cam-kết ("bản cam kết",
"08/ck-tncn"), matched anywhere on the page (not just heading lines); the ambiguous
"biên bản"/"hợp đồng" titles keep the #003 anti-over-split guard. Verified: packet 0
(Huỳnh Thị Thúy Phượng) 2 → 3 docs (Tra cứu thuế split out); packet 23 unchanged (4).
**Correction:** packet 0 has no Bản cam kết — its 4th document is a **Phụ lục đánh
giá chất lượng dịch vụ** (confirmed on p14). Document composition varies per CTV; the
earlier "same 4 documents" note was a skim error. The Phụ lục residual is tracked as #010.

## 010 — Rotated "Phụ lục" (SOW appendix) not segmented

**Observed:** packet 0's page 14 is a **Phụ lục đánh giá chất lượng dịch vụ** — a
rotated (90°) SOW/KPI table — which folds into the "Biên bản" tab instead of being
its own document.

**Cause:** the page is rotated, so 0°-OCR garbles its title/body; `segment_docs`
can't key on a recognizable heading. (Keyword classification, as used for #009,
can't recover a title the OCR never produced.)

**Fix direction:** detect page rotation (PyMuPDF/OSD) and re-OCR rotated pages
upright, or add a layout heuristic (a landscape/rotated page inside a portrait
packet → "Phụ lục"). Bigger than keyword matching.

**Status:** open (low priority) — cosmetic (tab grouping only; extraction/matching
unaffected).
