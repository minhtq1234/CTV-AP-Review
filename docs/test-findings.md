# Test findings / bug log

Running log of issues found while testing the upload → split → OCR → validate
flow on real submissions. Newest entries at the bottom. No PII in this file —
reference packets by STT / field, not by real values.

| ID | Area | Status | Summary |
|----|------|--------|---------|
| 001 | OCR / fields | open | MST and CCCD validated as the same value (see below) |

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
