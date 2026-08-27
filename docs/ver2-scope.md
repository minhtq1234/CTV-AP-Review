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

Two features. (An earlier revision of this doc listed a prerequisite fix — §2.0 below records
why it turned out not to apply here.)

### 2.0 NOT APPLICABLE to this base — the routed-source defect is `main`-only

Recorded so it is not re-derived, and because it explains a number in §4.

On the `main` lineage, `server/checklist.py` picks one source per value check by document
routing without checking whether that source has a value:

```python
src = next((s for s in sources if s and s.get("docId") == routed), None) or (sources[0] if sources else None)
```

Consequence, measured on the February case **on `main`**: 139 of the 175 checks reported as
unread had a readable value OCR had already extracted elsewhere in the packet; only 36 were
genuinely unread. Packet 0's CCCD sat on the BBNT at 0.91 confidence while the checklist
showed nothing read.

The routing was deliberate — `097bdc9 fix(ocr/checklist): value checks prefer routed-doc
source so B1 name lands on the contract`. Preferring an **empty** routed source over a
**readable** non-routed one, and then reporting "unread", is the unintended side effect.

**This base is unaffected.** `stable` has no `server/checklist.py` and no
`ChecklistPanel.tsx` (dropped via merge `e177cf7`; `server/cccd_ingest_test.py` even asserts
`"checks" not in manifest`). Its criteria engine handles the case correctly and says so in
`server/evaluate.py::_compare_reads`:

> An unreadable copy is excluded rather than counted as disagreement — that is what a reviewer
> does with an illegible page. Only when every copy is unreadable does the cell go `pending`.

Verified rather than assumed: across the February re-ingest on `stable`, **0 of 128 criteria
rows hid a value OCR had read**. No work here.

`main` and `stable` forked at `4955545` (27 Jul); `main` added 3 commits (docs + gitignore),
`stable` added 103. `main` is *not* an ancestor of `stable`.

### 2.1 GreenNode IDP for document-field extraction

Today IDP reads **CCCD cards only** (`server/cccd_idp.py`), opt-in behind two env vars, with
local Tesseract as the default reader (`server/pipeline.py`). Contract / BBNT / appendix
fields go through `pytesseract.image_to_data(lang="vie")` in `server/ocr_extract.py`.

Ver 2 extends IDP to those document fields.

**Shape — escalation, not replacement** (see §4 for why): Tesseract runs first; IDP is called
only where the local read is unusable; Tesseract stays primary, so there is no "network is
down" mode to design and most packet data never leaves the workstation.

**Built — everything except the transport's one unknown.**

| piece | where | status |
|---|---|---|
| escalation policy | `server/field_escalation.py` | done, 27 tests |
| IDP-as-OCR reader | `server/idp_words.py` | done, 15 tests; `parse_words` unverified |
| re-read loop | `ocr_extract._escalate_weak_fields` | done, 9 tests |
| pipeline wiring | `pipeline._page_reader` | done, off by default |
| doc_type discovery | `server/idp_probe.py` | **needs a live run** |

IDP is used as a **better OCR engine at the `words_by_page` seam**, not as a contract
understander: it returns text with boxes and the existing anchor/pattern logic does the rest.
That reuses all the Vietnamese-contract knowledge in `locate_field` instead of duplicating it,
and one escalated page serves every field on it rather than one call per field. The page sent
is the **display PNG already on disk**, so the returned boxes are already in display space —
no scale factor to get wrong, and they line up with the reviewer's highlight.

Targeting: a weak field carries the `docId`/`page`/`bbox` of the slot its value sits in
(that is what the located-but-unread hit is for), so escalation re-reads exactly those pages.
Measured cost on the real batches:

| batch | packets needing a 2nd read | pages sent to IDP |
|---|---|---|
| July | 25/41 | 50 of 362 doc-pages (**14%**) |
| February | 29/32 | 81 of 286 doc-pages (**28%**) |

Merge is **replacement per escalated page, not a union** — a union would leave a local garbage
read beside a good escalated one for the same page, and two readable copies that disagree is
exactly what `evaluate._compare_reads` treats as worst-wins, so it would turn a field the
escalation just fixed into a false mismatch.

Fallbacks: a reader that raises, returns nothing, or is pointed at a missing page all leave the
local read in place. A network problem must never make an ingest worse than not having called.

**The one open unknown.** `doc_type=ID` is the only value this codebase has ever sent, and it
selects the CCCD model — wrong for a contract page. Which `doc_type` gives a general page read,
and whether that mode returns **text runs** (what `parse_words` assumes) or **named fields**
(which would need a small mapper instead), cannot be established without a live credential.
`server/idp_probe.py` settles both in one run:

```
export GREENNODE_IDP_URL=...  GREENNODE_API_KEY=...
python3 server/idp_probe.py <a-contract-fee-page>.png
```

It tries a list of candidate doc_types, reports which return items with coordinates, and prints
the `export IDP_DOC_TYPE=` line to use. Until it has been run, IDP for document fields is wired
but unproven and stays off.

### 2.1a Cheap extraction fixes that come BEFORE spending IDP calls

Investigating `phi` (§5.3) showed the field's failures have **two independent causes**, and
only one of them is an IDP problem.

**Cause 1 — the anchor matches the section heading, and the lookahead is one line.**
`phi`'s anchor is `"phi dich vu"`. In a contract that phrase appears twice: the section
heading `ĐIỀU 2. PHÍ DỊCH VỤ VÀ THANH TOÁN`, and the clause `2.1. Phí dịch vụ: N đồng.`
OCR reliably reads the big bold heading but routinely drops "vụ" from the clause
(`Phí dịch 8.888.889 đồng.`), so **only the heading anchors** — and the heading has no number.
`locate_field` then searches the line, its reassembled row, and only `lines[idx + 1]`.

So a success depends on the fee happening to be the very next line:

| July page | anchor line | `idx+1` | result |
|---|---|---|---|
| p9 (packet 0) | `ĐIỀU 2. PHÍ DỊCH VỤ VÀ THANH TOÁN` | `Bộ 1; Phí dịch 8.888.889 đồng.` | reads — **by luck** |
| p17 (packet 1) | same heading | `IÍ` (an OCR fragment) | fails |

Measured over July's 9 failures, the fee sits 2–3 lines below the anchor. Note the line
grouping happens in *display* space (`scale_words` then `group_lines`, `y_tol=8`), so "lines"
here are display-space lines, not OCR-space ones.

**Done — `b7e2994`.** The lookahead is now per-spec (`spec["lookahead"]`, default 1) and `phi`
is the only spec that widens it, to 3. Confirmed end-to-end by re-ingesting July through the
real pipeline:

| field | before | after |
|---|---|---|
| `phi` | 32/41 | **40/41 — all 40 matching the roster, 0 wrong** |
| `hoten` / `mst` / `tk` / `ngaysinh` | 41 / 41 / 41 / 39 | unchanged |
| all fields | 235/246 (96%) | 240/246 (98%) |

It also makes the previously-passing 32 robust rather than accidental.

Two cautions for anyone repeating this measurement:

- **Ingest with `cccd.xlsx`**, not just the PDF and roster. Without it, `cccd` reads 38/41
  instead of 41/41 — 24 card-derived sources vanish and 3 packets lose their only readable
  CCCD source. The document-derived counts (`contract` 34, `bbnt` 26, `pit` 1) are identical
  either way, which is how that drop was distinguished from a regression.
- **`packet["pages"]` in `case.json` is `[first, last]`, a range — not a list of pages.**
  Indexing it per doc-relative page silently reads the wrong pages.

Remaining tail: **packet 38 only** (1 of 41). Its sole `phi` source doc is `bbnt-0` — it has no
contract source at all, so that is a document-segmentation problem, not a lookahead one.

**Cause 2 — the value is handwritten.** This is all 32 February packets. The anchor finds the
right clause (`2:Ì.. Phí dịch vụ:`), but the amount is written in blue pen on a ruled blank and
Tesseract's `vie` model returns nothing for it — the following line is handwriting noise
(`t_ ‹lam “=`). No anchor or lookahead change touches this. **Only a handwriting-capable
reader fixes it**, which is the genuine IDP case.

**Order of work:** Cause 1 is done. Scope IDP (§2.1) against what is actually left, which is
Cause 2 — the handwritten batches — plus the sub-`LOW_CONF` tail.

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

The gap between those two numbers is not OCR quality — it is `main`'s routing defect, §2.0.
It does not exist on this base, so **78% and 96% are the real numbers to plan against**; 9%
never described this codebase.

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
   earns a wider role than July alone suggested. See §4.

   The re-ingests behind §4 and §2.1a were deleted afterwards (446 MB). To recreate one, POST
   an existing case's own source files back through the API — **include `cccd.xlsx`**, or
   `cccd` will read low for the reason given in §2.1a:

   ```
   cd server/data/cases/<an-existing-case-id>
   curl -X POST http://127.0.0.1:8002/api/cases \
     -F "pdf=@input.pdf" -F "roster=@roster.xlsx" -F "cccd=@cccd.xlsx"
   ```

   Allow ~7 min for 32 packets, ~11 for 41, and restart the API first if server code changed —
   uvicorn here runs without `--reload`, so an in-memory old module will silently measure the
   old behaviour.
3. ~~Why is `phi` 0/32 on February but 32/41 on July?~~ **Answered and fixed 2026-08-27** —
   two separate causes, see §2.1a. February's fee is **handwritten** (a real IDP case); July's
   9 failures were an **anchor/lookahead defect**, fixed in `b7e2994`, taking July's `phi` to
   40/41 with every read matching the roster. Part of what looked like an IDP requirement was
   a local code fix. Still open within it: packet 38, which has no contract `phi` source at
   all (a segmentation problem).
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
