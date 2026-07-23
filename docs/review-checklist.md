# CTV payment-review checklist — requirements

Canonical, coded list of what the AP/Acc reviewer checks for each CTV payment
request, derived from the Acc team's checklist ("Chi phí CTV - Review Checklist").
This is the **product requirement** (the *what*); the designer-facing brief
(`design-brief-review-ui.md`) covers the *how*.

## Review model

- **One packet (one CTV) at a time.**
- Each packet's checks are in **two tiers**:
  - **Tier 1 — Preconditions (gates):** pinned to the **top**. The reviewer does these
    first. If any **fails**, they flag it and may **move straight to the next packet** —
    finishing the detail checks is **optional (their choice)**. Rationale: a
    structurally invalid document (wrong template, unsigned, missing, wrong person)
    makes reviewing its contents pointless.
  - **Tier 2 — Detail checks:** the value / consistency / temporal checks, worth doing
    once the gates pass.
- **Completeness rule:** the "must look at every item" requirement gates only the
  **Clear / OK-to-pay** outcome — **not** the send-back-at-gate path.

## Packet outcomes

- **Clear** — gates pass, all detail checks seen, no flags → OK to pay.
- **Send back — precondition failed** — a Tier-1 gate failed (rest optional).
- **Send back — detail issues** — gates pass, but Tier-2 flags exist.

## The checks (coded)

Codes follow the Acc sheet (section letter + item number). Method: **L&L** =
locate-and-look (tool finds the spot on the scan, human confirms by eye); **LLM** =
text-LLM extraction/summary aid (see below); **manual** = outside the tool.

| Code | Hạng mục | Verify | Type | Tier | Evidence | Method | Scope |
|------|----------|--------|------|------|----------|--------|-------|
| **G-DOC** | Đủ chứng từ | All required documents present in the packet | completeness | **Gate** | whole packet | L&L | ✅ |
| **G-ID** | Đúng người | Identity matches roster (CCCD; name fallback) — not the wrong CTV | identity | **Gate** | match key (OCR ↔ roster) | auto + L&L | ✅ |
| **D3** | Đúng template năm | PIT commitment uses the current year's template | temporal / version | **Gate** | Bản cam kết (+ reference template) | L&L | ✅ (no live site lookup) |
| **B3** | Chữ ký & con dấu (HĐ) | CTV sig + rep sig + Legal giáp lai present on contract | signature/seal presence | **Gate** | Hợp đồng | L&L | ✅ |
| **C2** | Chữ ký & con dấu (BBNT) | BBNT signed & sealed | signature/seal presence | **Gate** | BBNT | L&L | ✅ |
| **A1** | CCCD | Contract info matches the attached CCCD scan | cross-doc | Detail | Hợp đồng ↔ CCCD scan | L&L | ✅ |
| **A2** | MST | MST value consistent across documents | value consistency | Detail | Hợp đồng / Cam kết / Tra cứu thuế | L&L | ✅ (active-status lookup ⛔) |
| **B1** | Thông tin CTV | Section-A info filled correctly on contract | value consistency | Detail | Hợp đồng (↔ roster/CCCD) | L&L | ✅ |
| **B2** | Số tiền | Number and words agree on the contract | value consistency (internal) | Detail | Hợp đồng | L&L | ✅ |
| **B4** | Thời gian & nội dung | Period appropriate to the year | temporal | Detail | Hợp đồng | L&L | ✅ |
| **C1** | Thời gian & nội dung | BBNT period/work matches the contract | cross-doc + temporal | Detail | BBNT ↔ Hợp đồng | L&L | ✅ |
| **C3** | Đồng nhất nội dung | Work content consistent: contract ↔ bảng kê ↔ BBNT | cross-doc (3-way) | Detail | Hợp đồng + Bảng kê + BBNT | **LLM** + 3-way view | ✅ |
| **D1** | Thông tin & MST | Cam kết personal info + MST match the CTV file | cross-doc | Detail | Bản cam kết ↔ CCCD/Hợp đồng | L&L | ✅ |
| **D2** | Ngày tháng | Commitment date appropriate to the period | temporal | Detail | Bản cam kết | L&L | ✅ |
| **E1** | Bảng kê (no-invoice) | Bảng kê matches contract + BBNT | cross-doc (3-way) | Detail | Bảng kê + Hợp đồng + BBNT | **LLM** + 3-way view | ✅ |
| **A3** | Thông tin Bank | Old CTV: vs prior successful transfers · new CTV: sense-check | historical / heuristic | Detail | Hợp đồng + Acc transfer DB | — | ⏳ pending (needs Acc DB) |
| **F1** | Tính ZA (giá trị chi trả) | Compute payment: revenue-share, budget split, related eforms | business calculation | — | reports + eforms (FA-PA/LG-CM/FA-PM) | — | ⛔ out (manual) |

**Tier 1 (gates), top of every packet:** `G-DOC, G-ID, D3, B3, C2`.
**Tier 2 (detail):** `A1, A2, B1, B2, B4, C1, C3, D1, D2, E1`.
**Pending:** `A3`. **Out (manual/external):** `F1`, A2 active-status, D3 live lookup.

## Check-type notes

- **Signature/seal presence (B3, C2):** **locate-and-look only.** The tool navigates to
  the signature/seal block (anchored on printed labels) and the reviewer confirms
  presence. The tool does **not** judge authenticity, the right person, or whether the
  *giáp lai* is correct — those are human calls. No CV detection.
- **Content consistency (C3, E1):** the hard ones. The work content is **free text**
  across three documents, phrased differently — not a value to match. Approach:
  1. Locate the content region on each doc (contract SOW, bảng kê line, BBNT) via
     headings.
  2. A **text LLM extracts + normalizes/summarizes** each into a short comparable form.
  3. Show the three summaries **side by side** in a dedicated **3-way comparison view**
     (a new UI pattern — to be designed), each summarized point **linked back to its
     source region** on the scan.
  4. The reviewer judges "same work?" and flags. **The summary is a reading aid, never
     the verdict.**
  - **Model:** text LLM (the SOW/contract content is **typed**, so OCR is reliable —
    no vision needed), hosted on **GreenNode** (VNG's AI cloud → PII stays within VNG's
    trust boundary). Send **only the content region**, not identity fields; confirm
    GreenNode retention/logging. Specific model + endpoint pinned at build time
    (OpenAI-compatible hosted API).
- **Identity gate (G-ID):** reuses the existing match key — OCR'd CCCD vs roster
  (name fallback). A weak/failed match (name-only or unmatched) is a gate: verify it's
  the right person before anything else.

## Open items

- **A3 (bank vs history)** is blocked on the Acc team providing a database of prior
  successful transfers. Until then it's a manual/skipped check.
- **Reference template for D3** — to check "current year's template" without a live
  lookup, the tool needs the correct template(s) configured per year.
- **The 3-way comparison view (C3/E1)** is a new UI pattern — parked for design.
