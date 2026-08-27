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

A prerequisite fix, then two features.

### 2.0 Prerequisite — stop discarding reads the pipeline already made

`server/checklist.py` picks one source per value check by **document routing**, without
checking whether that source has a value:

```python
src = next((s for s in sources if s and s.get("docId") == routed), None) or (sources[0] if sources else None)
```

Measured on the February case: **139 of the 175 checks reported as unread had a readable
value that OCR had already extracted** on another document in the same packet. Only 36 were
genuinely unread. Example, packet 0:

| check | checklist picked | available but ignored |
|---|---|---|
| `A1` Số CCCD | `contract-0`, `''`, conf 0.0 | `bbnt-0`, `079189016370`, conf 0.91 |
| `B1` Họ tên | `contract-0`, `''`, conf 0.0 | `bbnt-0`, `Huỳnh Thị Thúy Phượng`, conf 0.95 |

Routing itself is legitimate — "Số CCCD khớp giữa chứng từ" wants the CCCD *as it appears on
the contract*. The defect is preferring an **empty** routed source over a **readable**
non-routed one, and then reporting the field as unread.

Fix shape: prefer a readable source on the routed document; fall back to a readable source on
another document **and attribute which document it came from**, so the reviewer is told
"the contract's value couldn't be read; the BBNT here reads X" rather than "nothing was read".

**Do this before 2.1.** Otherwise IDP will extract values that this same routing rule
discards, and the cost buys nothing for those 139 fields.

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

Taken 2026-08-27 against the live pipelines. All rows below use **one** metric —
`fields[].sources[]`, i.e. did OCR read a value for this field anywhere in the packet.

| batch | code | fields read | `phi` | `cccd` | median conf | below `LOW_CONF` |
|---|---|---|---|---|---|---|
| July (41 packets) | current stable | **235/246 (96%)** | 32/41 (78%) | 41/41 (100%) | 0.93 | 91/426 (21%) |
| February (32 packets) | current stable | **149/192 (78%)** | **0/32 (0%)** | 25/32 (78%) | 0.92 | 28/158 (18%) |
| February (32 packets) | old code, ingested 28 Jul | 150/192 (78%) | 0/32 | 26/32 | 0.94 | 29/174 (17%) |

**February is a genuinely harder submission**, and stable's August OCR fixes closed none of
that gap (149 vs 150 is noise). `phi` — a payment amount — is unread across all 32 packets.

**Beware the metric.** An earlier claim that February read at "9%" and that extraction was the
bottleneck was an artifact of measuring `checks[].source.value` instead. Same case, same code:

    fields[].sources[]        156/192  (81%)
    checks[].source.value      17/192   (9%)

The gap between those two numbers is not OCR quality — it is the routing defect in §2.0.

**Why IDP is still an escalation, but a substantial one:** on July the trigger (unread, or
below `LOW_CONF`) would fire on ~20% of fields; on February, ~35–40%. That is real work rather
than marginal work, and it justifies IDP — but it does not justify replacing Tesseract, which
reads 78–96% correctly and keeps that data on the workstation.

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
2. ~~Does a poor submission still read badly on `stable`?~~ **Answered 2026-08-27** — yes.
   February reads 78% vs July's 96%, `phi` 0/32, and the August fixes did not help it. IDP
   earns a wider role than July alone suggested. See §4. Re-ingested as case
   `8ee0c3a88104466cad20cccbfbf0b25a` (~7 min for 32 packets) if the numbers need rechecking.
3. **Why is `phi` 0/32 on February but 32/41 on July?** Unknown, and worth an hour before
   spending IDP calls on it — a labelling or layout difference may be cheaper to fix than a
   network call per field. `phi` is the highest-value field in the packet.
4. **Governance for sending payment documents to GreenNode.** CCCD-only IDP was one thing;
   document-field IDP sends contracts and BBNT off the workstation. The original brief
   allowed GreenNode processing *"subject to confirmation of internal logging, retention and
   access controls."* Current standing instruction is to make it work first and settle
   privacy later — recorded here so the decision is explicit, not assumed.
5. **What discriminating columns does the table need?** Unanswered; it decides whether 2.2 is
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
