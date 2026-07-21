# Test findings / bug log

Running log of issues found while testing the upload → split → OCR → validate
flow on real submissions. Newest entries at the bottom. No PII in this file —
reference packets by STT / field, not by real values.

| ID | Area | Status | Summary |
|----|------|--------|---------|
| 001 | OCR / fields | resolved | MST/CCCD kept independent; MST reads MSTTNCN; now doc-labeled |
| 002 | alignment | resolved | Now align by OCR'd CCCD (name fallback), not position |
| 003 | doc segmentation | resolved | Packet split into per-document EvidenceDocs; sources doc-labeled |
| 004 | multi-doc sources | open | A field should be navigable on EVERY doc it appears on, incl. unread |

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

**Status:** open — enhancement; realizes the original "check each field across
multiple documents" goal on the real OCR pipeline.
