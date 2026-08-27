# Ver 2 — scope

**Status:** agreed 2026-08-27. Not started.
**Base branch:** `stable/2026-08-25-cccd-idp`
**Companions:** [`design-brief-review-ui.md`](design-brief-review-ui.md) (the UI philosophy),
[`review-checklist.md`](review-checklist.md) (what gets checked),
[`ui-improvements.md`](ui-improvements.md) (backlog, separate from this scope).

---

## 1. Where the numbering stands

Only one version has ever been named in this repo:

| | evidence |
|---|---|
| **v1** — shipped | tag `v1-stable-2026-07-28`; branch `ver1` carried it to `9aa66b8` (25 Aug) |
| everything since | unversioned work on `main` → `stable/2026-08-25-cccd-idp`; never tagged |

No `ver2`/`ver3` branch, tag, or doc existed before this file, so no number after 1 was
consumed. "Ver 3" was used loosely in conversation during the criteria-engine work; it
referred to work in progress, not a release. **The next release is ver 2.**

The current `stable` build is *not* ver 2 — it is the base ver 2 is built on. It becomes
ver 2 when the scope below lands. **Tag it on ship** as `v2-stable-YYYY-MM-DD`, matching the
v1 convention, so the number lives in the repo rather than in conversation.

## 2. What ver 2 adds

Exactly two things.

### 2.1 GreenNode IDP for document-field extraction

Today IDP reads **CCCD cards only** (`server/cccd_idp.py`), opt-in behind two env vars, with
local Tesseract as the default reader (`server/pipeline.py`). Contract / BBNT / appendix
fields go through `pytesseract.image_to_data(lang="vie")` in `server/ocr_extract.py`.

Ver 2 extends IDP to those document fields.

**Recommended shape — escalation, not replacement** (see §4 for why):

- Tesseract runs first on every field.
- IDP is called **only** where Tesseract returned no value, or returned one below
  `LOW_CONF` (0.7, `src/logic/verdict.ts`).
- Tesseract stays the primary reader, so there is no "what if the network is down" mode to
  design, and most packet data never leaves the workstation.

**Not yet decided** — see §5.

### 2.2 Table view for the packet list

The packet list is currently a card grid (`src/components/CaseDetail.tsx`). Ver 2 replaces
it with a table, as `ver1` has. `ver1`'s columns were:

    STT · Họ và tên · Cam kết thuế · Chứng từ · Kết quả AI · Trạng thái · Kết quả kiểm tra · Phạm vi trang

Port the *form*, not the content. Two defects observed in `ver1`'s table must not come with
it:

- **`Kết quả AI` asserted a verdict** (`Không hợp lệ`). The tool does not judge the packet —
  see the philosophy in the design brief. State findings, not conclusions.
- **24 of 25 rows read identically**, so the table gave no basis for triage. A table is only
  worth the change if its columns discriminate between packets.

Keep the existing filter pills (`Tất cả / Chưa xem / Đang xem / Đã xong / Flagged`) and
`Cần chú ý trước`; `ver1`'s `Flagged` count contradicted its own summary line and should not
be copied.

## 3. Already built — do not re-do

Both of these were on the original ver 2 wish-list and already exist on `stable`:

| item | where |
|---|---|
| Grid view for packet details | `src/components/PacketGrid.tsx`, model in `src/logic/packetGrid.ts` (`match`/`review`/`mismatch`/`na`) |
| Full-screen doc view on clicking a check mark | each grid cell is a `<button>` → `onOpenEvidence(fieldKey, sourceIndex)` → `PacketEvidenceDrawer` at `width: 100vw` |

The drawer was ported from `ver1` already (`src/styles.css`: *"packet grid view + evidence
drawer (ported from ver1)"*).

## 4. Measurements that shaped this scope

Taken 2026-08-27 against the live pipelines. **The two numbers differ by codebase — do not
mix them up.**

**`stable`, July case (41 packets) — Tesseract only:**

    235 / 246 field slots read   (96%)      median confidence 0.93
      hoten 41/41   cccd 41/41   mst 41/41   tk 41/41
      ngaysinh 39/41 (95%)       phi 32/41 (78%)
    reads at/above LOW_CONF 0.7: 335/426

**`main`, February case (32 packets) — older pipeline, lacks stable's OCR + splitter fixes:**

    17 / 192 value checks read   (9%)
    autostatus: 175 review · 11 match · 6 mismatch

`main`'s 9% is **not** representative of `stable`. An earlier claim that "extraction is the
bottleneck" was based on it and is wrong for the shipping codebase.

**Why the escalation shape:** at 96%, IDP has ~4% of fields to gain outright, plus the
low-confidence tail (91 of 426 reads below `LOW_CONF`). `phi` at 78% is the clear
beneficiary. Spending an IDP call on every field to win that would be poor value and would
send far more packet data off the workstation than necessary.

**Prior evidence IDP does help where Tesseract struggles** — recorded in
`server/pipeline.py` for CCCD cards: *26 of 41 people resolved locally versus 40 of 41 via
IDP, with no false reads either way.*

**Confidence is a reliable signal.** On `main`'s case all 11 `match` results carried
confidence 0.94–0.96 and all 6 `mismatch` results 0.00–0.16 — and every one of those 6 was an
OCR failure (`NujI Van` for a name, a company MST for a CCCD, a 6-digit fragment for a bank
account, a mobile number for a CCCD), not a discrepancy in the paperwork. This is why the
escalation trigger is confidence-based, and why a disagreement is only reported as a
disagreement when the read behind it was confident.

## 5. Open questions

1. **IDP mode not finally decided.** §2.1 records a recommendation, not a decision.
2. **Does a poor submission still read badly on `stable`?** The February batch has not been
   measured on `stable` — only on `main`. If February reads ~96% on `stable` too, IDP's
   remaining value is mostly `phi` and the low-confidence tail; if it reads badly, IDP earns
   a wider role. **Measure this before building 2.1.**
3. **Governance for sending payment documents to GreenNode.** CCCD-only IDP was one thing;
   document-field IDP sends contracts and BBNT off the workstation. The original brief
   allowed GreenNode processing *"subject to confirmation of internal logging, retention and
   access controls."* Current standing instruction is to make it work first and settle
   privacy later — recorded here so the decision is explicit, not assumed.
4. **What discriminating columns does the table need?** Unanswered; it decides whether 2.2 is
   worth doing. See the `ver1` defect in §2.2.

## 6. Out of scope

- Re-porting anything from `ver1` beyond the table view's form. `ver1` is 213 commits
  divergent and has no criteria engine, Tổng hợp tab, overrides, or splitter fixes.
- The `ui-improvements.md` backlog (U1–U5), unless a specific item is pulled in explicitly.
- Row-level Bảng Kê Thu Mua parsing — measured and deliberately parked earlier.

## 7. The standing constraint

Unchanged from v1 and the design brief, and neither item above may weaken it:

> The AI finds the data and marks its position. The reviewer validates with their own eyes on
> the scan, flags what doesn't reconcile, and a report goes back for resubmission. The
> reviewer never approves or rejects, and never edits data. The tool states findings, never
> verdicts.
