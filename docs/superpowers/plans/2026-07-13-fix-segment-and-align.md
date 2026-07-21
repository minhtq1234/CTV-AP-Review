# Fix: document segmentation + identity-based alignment (#001–#003) — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development for pure logic; verify the pipeline offline on real packets. Checkbox (`- [ ]`) steps.

**Goal:** Make a packet render as its real constituent documents, and pair each packet to the correct roster row by identity (OCR'd CCCD) instead of by position — eliminating the wholesale false-mismatch when PDF order ≠ roster order.

**Findings addressed** (see `docs/test-findings.md`):
- **#003** — packet's ~4 documents are bundled into one "Hồ sơ"; sources unlabeled.
- **#002** — packet matched to wrong roster row (position-based) → all fields red.
- **#001** — MST vs CCCD: keep independent; MST reads MSTTNCN line; doc labels disambiguate. No equality rule.

**Files:** `server/ocr_extract.py`, `server/ocr_extract_test.py`, `server/pipeline.py`, `server/README.md`. PII: outputs to temp/scratch only; commit code only.

---

## Design

### A. Document segmentation (#003)
Each packet page already gets OCR'd. Classify each page by the title text in its
top region and group consecutive pages into documents.

- `classify_page(text) -> (kind, label) | None` — accent-insensitive keyword match on the page's OCR text (check the top ~1/3 first). Table (first match wins):
  - `hop dong dich vu` → (`contract`, "Hợp đồng dịch vụ")
  - `bien ban` (or `nghiem thu`, `thanh ly hop dong`) → (`bbnt`, "Biên bản nghiệm thu")
  - `ban cam ket` (or standalone `cam ket`) → (`commitment`, "Bản cam kết")
  - `phu luc` → (`pit`, "Phụ lục")
  - `tra cuu` (or `bang thong tin tra cuu`, `nguoi nop thue tncn`) → (`pit`, "Tra cứu thuế")
  - `can cuoc cong dan` → (`id_front`, "CCCD")
  - else `None` (continuation page of the current document)
- `segment_docs(page_texts: list[str]) -> list[{kind,label,pages:list[int]}]` — walk pages in order; a page that classifies starts a new doc; unclassified pages append to the current doc; if the first page is unclassified, open a default `contract` doc. `pages` are packet-relative indices.
- In `ocr_packet`, build **one `EvidenceDoc` per segment** (`id = f"{kind}-{n}"`, its `label`, and the display-PNG `pages` for that segment). Each field **source's `docId`** = the segment its page falls in, and `page` = index within that segment. Dedupe identical `(docId, value)` sources.

### B. Identity-based alignment (#002)
Move roster pairing from position to OCR'd CCCD, with a name fallback.

- In `pipeline.py`, build once: `roster_by_cccd = {digits(row.cccd): row}` and `roster_by_name = {norm(row.name): row}` from the roster rows.
- `ocr_packet` returns identity too: `{cccd, name}` = the best (highest-confidence) OCR'd CCCD and name for the packet. Expected values are NOT filled in `ocr_packet` (identity isn't known yet) — sources only.
- `match_roster(cccd, name, by_cccd, by_name) -> (row | None, how)`:
  1. exact `by_cccd[digits(cccd)]` → (row, "cccd")
  2. else `by_name[norm(name)]` (name fallback — needed so a roster row with a *seeded CCCD typo* still aligns by name, then shows the CCCD mismatch) → (row, "name")
  3. else (None, "unmatched")
- `pipeline` then: match → fill each field's `expected` from the matched row (empty if unmatched) → set folder `name`/`product` from the row (or `name=None` + flag `roster-unmatched` if unmatched) → write manifest.

This makes the pairing robust to PDF/roster order differences AND keeps the seeded-error demo working (name fallback → CCCD field still flags).

### C. #001 disposition
No equality rule. MST keeps its MSTTNCN-family anchors (reads the tax-code line, independent of CCCD). With B/A, MST sources now carry a document label, so it's visible they come from the MSTTNCN line — the redundancy is acceptable and correct. Just ensure identical same-doc MST/CCCD sources are deduped (from A).

---

## Tasks

### T1 — `classify_page` + `segment_docs` (pure, TDD)
- [ ] Failing tests in `ocr_extract_test.py`:
  - `classify_page("... HỢP ĐỒNG DỊCH VỤ ...")` → kind `contract`; `"BIÊN BẢN NGHIỆM THU ..."` → `bbnt`; `"BẢN CAM KẾT"` → `commitment`; `"PHỤ LỤC ..."` → `pit`; `"BẢNG THÔNG TIN TRA CỨU ..."` → `pit`/"Tra cứu thuế"; a body-text page → `None`.
  - `segment_docs(["HỢP ĐỒNG DỊCH VỤ..", "..body..", "..body..", "BIÊN BẢN NGHIỆM THU..", "..body..", "BẢN CAM KẾT..", "BẢNG THÔNG TIN TRA CỨU.."])` → 4 docs with page groups `[0,1,2],[3,4],[5],[6]` and the right kinds/labels. First-page-unclassified → default contract.
- [ ] Implement; run → `ALL OK`.
- [ ] Commit `feat(ocr): classify_page + segment_docs — split a packet into documents`.

### T2 — `ocr_packet` emits per-document sources + identity (refactor)
- [ ] Refactor `ocr_packet(pdf_path, start, end, out_dir, ...)` to: render display pages; OCR each; `segment_docs`; build one `EvidenceDoc` per segment; extract field sources with `docId`/`page` pointing at the owning segment; dedupe `(docId,value)`; return `{"folder": {docs, fields(with empty expected)}, "identity": {"cccd":..., "name":...}}` (do NOT fill expected here, do NOT require a roster_row). Keep MST anchors as-is.
- [ ] Import check `python3 -c "import ocr_extract"`; keep prior pure tests green (adjust any that assumed the single-doc shape).
- [ ] Commit `refactor(ocr): per-document sources + packet identity; expected filled by caller`.

### T3 — `match_roster` (pure, TDD) + pipeline alignment
- [ ] Failing tests (put roster matching in `pipeline.py`, test via `pipeline_test.py` or inline `ocr_extract_test.py` if the helper lives there — keep it importable and pure):
  - exact CCCD hit → (row, "cccd"); CCCD miss + name hit → (row, "name"); both miss → (None, "unmatched"); `digits()` strips spaces/punct; `norm()` accent-insensitive name.
- [ ] Implement `match_roster` + wire `pipeline.run_pipeline`: build `by_cccd`/`by_name`, for each packet call `ocr_packet` → `match_roster(identity...)` → fill `expected` from the row (helper `fill_expected(fields, row)`), set folder name/product or `roster-unmatched` flag → write manifest.
- [ ] The split preview (detect_packets by-order name) is now overridden by the CCCD-matched identity in the final packet/result; ensure the returned `packets[].name` and the manifest name are the matched ones.
- [ ] Commit `feat(server): align packets to roster by OCR'd CCCD (name fallback), not position`.

### T4 — Verify offline on the real, previously-misaligned pair
- [ ] Scratch driver (NOT committed): run the pipeline pieces on the two adjacent packets that were mispaired (the Nguyễn Thảo Ly / Nguyễn Đào Hồng Hạnh region) with the real roster. Assert: the packet whose docs are Hồng Hạnh's resolves (by CCCD) to Hồng Hạnh's roster row (name + CCCD match green), and the other resolves to its own row — i.e. no cross-pairing. Also assert each packet now has **multiple EvidenceDocs** with distinct labels, and a field found in 2 documents shows 2 sources with **different docIds/labels**. Print masked pass/fail only.
- [ ] Report: per-packet #docs + labels, identity match `how` (cccd/name/unmatched), and that the mispaired pair is fixed. No PII, no committed output.

## Self-Review
- Coverage: #003→T1/T2 (segmentation + per-doc sources), #002→T3 (CCCD match + fallback + unmatched flag), #001→T2 (MST independent + dedupe). Verify→T4.
- Types: `EvidenceDoc{id,kind,label,pages}` and `CtvSource{docId,page,value,bbox,confidence}` unchanged from `src/ctv/types.ts`; `ocr_packet` new return `{folder,identity}`; `match_roster(cccd,name,by_cccd,by_name)->(row|None,how)`.
- Placeholder scan: contracts + concrete tests given; the OCR/render internals reuse existing verified code.
