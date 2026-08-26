# Validation flow — design

**Status:** design, not yet implemented
**Sources:** `Checklist_Binhnt10.xlsx` sheet *Requirement CTV Remove* (24 per-CTV
criteria + #28) · `LOGIC.md` / `ctv-detail-phuong.html` (artifact
`57fdbb0b`) · this repo's pipeline

---

## 1. What this bridges

The prototype and this codebase are complementary halves of the same product.

**The prototype supplies the target:** 25 per-CTV criteria in five display
groups, the matrix-versus-card presentation, a five-state result vocabulary,
evidence-on-click, and the split of five roster-level criteria into a separate
Tổng hợp tab. Its own §0 states that everything computational in it is
hand-typed — `META / VALUES / ISSUES / IMG_MAP` are constants, and §5.4 says
outright that the comparison functions do not exist yet.

**This codebase supplies those functions:** packet splitting, document
classification, field location with bounding boxes, roster parsing, GreenNode
IDP card reading at 40/41, duplicate-identity detection, roster validation,
persistence, reporting.

So the work is not "build the prototype". It is **put the engine behind the
prototype's UI**, and in doing so replace hand-typed results with computed ones.

### 1.1 The one inversion that matters most

`LOGIC.md` §6.2 documents its own most dangerous property:

```
cellStatus(stt, doc):
    if ISSUES[key] exists:  return ISSUES[key].status
    else if VALUES[stt] !== undefined:  return 'ok'     ← default
    else: return 'pending'
```

and warns: *"'Có giá trị trong VALUES' không có nghĩa là 'đã được xác minh
khớp'."* A value existing and nobody having flagged it yields `ok`.

**In v2 that default inverts.** A cell is `ok` only when a comparator ran and
matched. No comparator, no value, or a comparator that could not decide →
never `ok`. Silence must not read as agreement; that is the false-clear path
the whole product is built to avoid.

---

## 2. Criteria registry

One record per criterion, in code, keyed by Acc's STT so the numbering stays
traceable to the source workbook.

```python
@dataclass(frozen=True)
class Criterion:
    stt: int
    label: str            # as Acc writes it
    group: str            # display section 01-05
    docs: tuple[str, ...] # which documents it compares across
    how: str              # Acc's natural-language rule, verbatim
    kind: Kind            # which evaluator runs it
    render: Render        # "matrix" | "card"
    params: dict          # kind-specific (format, parts, inputs, formula)
```

`render` is stored, not derived. The prototype made editorial judgements no rule
reproduces — folding #19 into #14's card, #29 into #09's row, #15–#17 into one
PIT card, lifting #06 and #12 out of the matrix. Those choices are good and
should be preserved as data.

`how` is carried verbatim and shown to the reviewer. It is the instruction a
human follows when the tool abstains, and it is what makes an abstention
actionable rather than a dead end.

---

## 3. Five evaluator kinds cover all 25 criteria

Derived from Acc's own `Loại kiểm tra` column.

| Kind | Criteria | What it does |
|---|---|---|
| `compare` | 01 02 03 04 05 07 08 09 10 11 13 27 | one value must agree across `docs`; optional format rule and required-parts rule. **Built**; 01 02 03 05 07 run today, the rest await extraction (§3.6) |
| `compute` | 12 14 15 16 17 | recompute from named inputs and compare against what the documents state. **Built**; 14 15 16 17 run today, 12 awaits date extraction |
| `presence` | 21 22 23 24 25 28 | signature / seal / content present — the tool navigates, the human decides |
| `external` | 06 | an artefact the reviewer supplies answers it (MST lookup screenshot) |
| `conditional` | 18 | applies only if a document exists; its absence is itself an input to another criterion |

Twelve + five + six + one + one = 25.

### 3.1 `compare`

```python
def compare(criterion, extracted: dict[str, Value], reference: Value) -> dict[str, Cell]
```

`extracted` is per-document; `reference` is the bảng kê value, which the
prototype shows verbatim in its Excel column rather than as a tick — keep that,
it gives the reviewer something to read rather than trust.

Comparison is kind-aware, reusing what already exists in `src/logic/verdict.ts`
and extended there on 2026-08-25: personal names compare with diacritics folded
but **word count significant**, so `Lê Thị Thu Hà` ≠ `Lê Thị Thu Hà Vy`;
organisation names keep the looser containment rule. A tone-mark-only difference
resolves to `rv`, never `ok` — Tesseract drops Vietnamese diacritics constantly,
but so does the gap between two real people.

`params.format` validates shape: #02 twelve digits (or an 8-character passport
for the foreign branch), #03 `dd/mm/yyyy`, #05 ten or twelve digits, #07
digits-only preserving leading zeros.

`params.parts` handles the two criteria whose rule is "must contain N things":
#08 bank name / branch / province, #13 amount / payment term / start point /
method / receiving account.

### 3.2 `compute`

Never trust a displayed formula. `LOGIC.md` #17 is explicit: *"Tính lại cho từng
CTV, không chỉ kiểm tra công thức hiển thị trong Excel."*

- **#17** `Gross − PIT = Net`, recomputed; state the gap when it differs
- **#14** Gross agreement across Hợp đồng / BBNT / Bảng Kê Thu Mua / Excel
- **#12** day count from #10 and #11, one number, not per-document; `≥ 1 month`
  raises a warning and never a conclusion
- **#15** the PIT rule — see §7, this one is **not** ours to decide
- **#16** Net positive and equal to the requested payment

`server/roster_checks.py` already implements #17, #16 and the #15 zero-without-
basis case at roster level, with header-based column location so it handles both
the February and July layouts.

### 3.3 `presence` — never automatically `ok`

Six criteria concern signatures and seals. Acc's checklist types them
`Chữ ký + dấu` and the product's stance has always been locate-and-look: the
tool navigates to the block, the reviewer confirms. It does not judge
authenticity, signer authority, or whether a *giáp lai* is correct.

So a `presence` cell starts at **`rv`** and only becomes `ok` or `no` through a
human decision recorded as an override (§6). Six of 25 criteria therefore open
amber on every packet. That is correct, not a defect — the prototype showed them
green because a person had already looked.

### 3.4 `external`

#06 needs the MST's active status. Earlier scoping marked this out of reach
because it implied a live call to `tracuunnt.gdt.gov.vn`. The prototype resolves
it neatly: *kết quả tra cứu MST* is one of the seven documents the reviewer
supplies. So the criterion reads a supplied artefact — no live lookup, no
network dependency in the pipeline.

### 3.5 `conditional`

#18 applies only when a `Cam kết 08/CK-TNCN` is in the packet. Its **absence is
an answer**, and it feeds #15: no commitment means the withholding rule applies.
The prototype models this correctly — #18 as `na` with a stated reason, and the
PIT card citing it as its input.

### 3.6 What the engine found, first run

Over all 36 July packets — 900 criterion cells: **86 ok · 142 no · 249 rv · 48
na · 146 missing · 229 pending**. Two things in that are worth recording.

**The engine's first real output is a diagnosis of the splitter.** #01 Họ và tên
reports `no` on 32 of 36 packets, and #07 Số tài khoản on 35 of 36. That looked
like the comparators being too strict, so the disagreements were measured:

| Field | Exact | 1 digit apart | 4+ digits apart |
|---|---|---|---|
| CCCD | 35 | 2 | 20 |
| Số TK | 30 | 1 | 42 |

Not OCR noise — different values. And the names name the pattern: `Lê Thanh Hải`
expected, `Đinh Hữu Phúc` read; `Lý Gia Huy` expected, `Lê Thanh Hải` read. Each
packet carries the tail of the **previous** CTV's documents. Packet 0 holds two
contracts and a BBNT naming a third person. The boundaries are off, and the
matrix is what makes that visible at scale.

So the comparators stay strict. A fuzzy tier for identity numbers would have
softened 3 cells out of 900 and hidden nothing useful.

**The splitter is fixed** (§3.7). The matrix was right; the packets were wrong.

### 3.7 The splitter fix the matrix prompted

The root cause was not in the splitter's arithmetic. Tesseract reads the
contract's first page as

    ĐÔNG
    HỢP DỊCH VỤ

hoisting `ĐỒNG` out of `HỢP ĐỒNG DỊCH VỤ` onto its own line, so the phrase
keyword never matched and **every contract first page went unclassified**. With
no document landmark, `detect_packets` fell back to band recurrence, whose seed
locked onto a *mid-contract* page — the fourth of each eight-page block.

`snap_covers_to_starts` walks each cover back to the nearest page that starts a
packet, then requires the offsets to agree before moving anything. Each
submission has its own offset, which is why it is measured rather than assumed:

| Submission | Covers before | Starts after | Offset | Packet lengths |
|---|---|---|---|---|
| July | 12, 20, 28 | 9, 17, 25 | 3 | 7–16, median 8 |
| February | 8, 16, 24 | unchanged | **0** | 7–9, median 8 |
| PUBGm | 33, 39, 45 | 29, 35, 41 | 4 | **all 6** |

February's boundaries were never broken, and the fix is a no-op there — which is
the property that made it safe to ship.

**What the re-ingest showed.** July re-ingested in 639s, and the boundary error
turns out to have been the cause of almost every finding the matrix reported:

| | Before | After |
|---|---|---|
| Roster rows matched by two packets | **9** | **0** |
| `no` cells (of 900) | 142 | **50** |
| #01 Họ và tên `no` | 32/36 | **7/36** |
| #02 Số CCCD `no` | 18/36 | **8/36** |
| #03 Ngày sinh `no` | 15/36 | **6/36** |
| #05 MST `no` | 21/36 | **7/36** |
| #07 Số tài khoản `no` | 35/36 | **7/36** |
| #31 duplicate payment | `no` — 9 CTV / 18 gói | **`ok`** |

The nine people who appeared to have two complete packets each had none: their
packets held the neighbouring CTV's documents, so identity matching put two
packets on one roster row. `matched` fell 36 → 35 because one packet now
genuinely matches nobody, which is more honest than being assigned a row that
was already taken.

The seven remaining #01 findings account for completely: five are the over-long
packets below, and two are single-document name reads that failed while the
packet's CCCD and cam kết agree — a field-extraction problem, and exactly what
the matrix exists to put in front of a reviewer.

### 3.8 Covers that were never found

A cover can also be missed outright, leaving one packet holding two CTVs'
documents. July had five: 14-16 pages against a typical 8, which is why 36
packets came back for 41 roster rows. Each one had **exactly one** contract page
in its interior, sitting where the boundary belongs.

`insert_missed_starts` searches only packets at least half again the typical
length, and requires a candidate to leave at least half a packet on both sides so
a stray title page cannot slice off a fragment. All three submissions now match
their roster counts:

| | Roster | Covers found | Final packets | Offset | Inserted | Lengths |
|---|---|---|---|---|---|---|
| July | 41 | 36 | **41** | 3 | 5 | 7-9 |
| February | 32 | 32 | **32** | 0 | 0 | 7-9 |
| PUBGm | 25 | 25 | **25** | 4 | 0 | all 6 |

**The baseline is the mode, not the median.** A submission where several packets
are merged drags the median towards the merged length and hides them — for
lengths `[8, 8, 16, 16]` the median is 16 and nothing would be found. Packet
sizes cluster tightly around the template's, so the most common length *is* the
single-CTV length.

An inserted boundary was never detected as a cover, so `near-threshold` says
nothing about it; `reconcile` takes `None` for such a packet and flags it
`inferred-boundary`, so a reviewer can see which boundaries came from a document
title rather than the cover cadence. The case header reports both adjustments —
`36 gói được cắt lại sớm hơn 3 trang · 5 gói bị gộp đã tách ra` — because
re-cutting a packet changes which pages belong to whom and should never be
silent.

A long packet with **no** document start inside is left alone: one CTV really can
have more documents than the rest.

**Both fixes, re-ingested.** July now returns 41 packets for 41 roster rows, 40
matched, 0 duplicate identities:

| STT | original | phase fix | both fixes |
|---|---|---|---|
| #01 Họ và tên | 32 | 7 | **2** |
| #02 Số CCCD | 18 | 8 | **5** |
| #03 Ngày sinh | 15 | 6 | **1** |
| #05 MST cá nhân | 21 | 7 | **2** |
| #07 Số tài khoản | 35 | 7 | **2** |
| #14 Gross | 7 | 3 | **0** |
| **`no` cells** | **142** | **50** | **25** |

What remains is no longer about boundaries. The two #01 findings are
single-document name reads that failed while that packet's CCCD and cam kết
agree, and #15's thirteen are zero-PIT rows without a cam kết — a real finding,
and the count rose from twelve only because there are now 41 packets rather than
36. Extraction and the checklist, not splitting.

**A partial snap is worse than none.** Before the classification fixes below,
PUBGm had 19 of 25 covers report offset 4 and 6 report 0; snapping only the 19
left a two-page packet in the split. The offset is a property of the
submission's document template, so the guard requires 80% agreement *among
covers that found a start* — a cover that found nothing is a failed page read,
not evidence of a different offset — and applies one offset to all of them.

Two classification defects found on the way, both of the same shape: the generic
`hợp đồng dịch vụ` beating a specific title.

- `Biên bản thanh lý hợp đồng dịch vụ` classified as a **contract**, as did
  `Biên bản nghiệm thu hợp đồng dịch vụ` and `Phụ lục hợp đồng dịch vụ`.
- Page 45 of the PUBGm submission is a BBNT whose title OCR scrambled and whose
  next line cites `Căn cứ Hợp Đồng Dịch Vụ số đã ký`. The citation matched, and
  invented a packet start.

Headings that name the document's own class now come first. A false `contract`
is the expensive direction — it invents a boundary; a false `bbnt` only means a
boundary is not found and the cover stays put.

**Coverage is bounded by extraction, not by the engine.** Six fields are
extracted today, so 8 criteria can be compared and the rest report `pending`
with a stated reason — #08 needs bank branch and province, #09–#13 need service
descriptions and dates, #27 needs VNG's own particulars. Those are extraction
work, and the matrix fills in as it lands.

Two truthfulness defects the real data exposed, both fixed:

- `fuzzy` has two causes — accent-folded-equal, and a genuinely different string
  that happens to be close — and the note described both as *"chỉ khác dấu hoặc
  chữ hoa/thường"*. For the second that is simply untrue about what is on the
  page. `compare_values.fuzzy_reason` separates them.
- Copies of one document disagreeing **with each other** were reported only when
  the cell was already a mismatch. Two contracts naming two people is a finding
  about the packet whatever the verdict against the bảng kê is.

---

## 4. Status model

Adopt the prototype's vocabulary; it is better than what this codebase has,
because it distinguishes *not applicable* from *document absent* from *needs a
human* — distinctions that `review` / `unread` currently collapse.

| Status | Glyph | Meaning | Reached when |
|---|---|---|---|
| `ok` | ✓ | agrees | a comparator ran and matched |
| `no` | ✕ | does not agree | a comparator ran and differed |
| `rv` | ! | needs a human | ambiguous compare, low confidence, or any `presence` criterion |
| `na` | – | not applicable to this packet | `conditional` unmet, or document not in `criterion.docs` |
| `missing` | ⊘ | document should be here and is not | required document absent from the packet |
| `pending` | ? | not evaluated | no value extracted, or no comparator for this pair |

Two notes carried from the prototype's own findings. `missing` exists in its CSS
and `openEvidence()` but no data uses it (§16 item 9) — in v2 it becomes live,
because packets genuinely arrive incomplete: 24 of 32 February packets have no
cam kết. And a cell for a document not listed in `criterion.docs` renders as a
static dash and is **not clickable**, distinct from a clickable `na` that can
explain itself.

### 4.1 Aggregation — resolves Open Question #8

**Count by criterion, not by cell.** The prototype's own header proves this is
the intent: `23 Khớp / 1 Cần review / 1 Không áp dụng` sums to 25, its criterion
count. Counting cells would make a criterion spanning five documents five times
as important as one spanning a single document.

Per criterion, **worst wins**, in this order:

```
no  >  missing  >  rv  >  pending  >  ok        (na excluded from the rollup)
```

`missing` outranks `rv` because an absent document is a gate failure, not a
question. `na` is counted and displayed separately — "not applicable" is
sometimes the finding, as with 24 of 32 packets lacking a cam kết.

---

## 5. Evidence

Every non-`na` cell must be able to answer "where did you get that?". The
prototype's rule — *"Bấm vào ô ma trận hoặc giá trị có gạch chấm để xem đúng
trang chứng từ gốc"* — is the product's core promise, and the pipeline already
produces what it needs: page index plus bounding box per located field.

```python
@dataclass(frozen=True)
class Evidence:
    document_id: str
    page: int
    bbox: Bbox | None       # None when the field was never located
    value: str              # what was read; "" when illegible
    confidence: float | None
    provenance: str         # "ocr" | "idp" | "roster" | "override"
```

`provenance` is not decoration. A value read by IDP at 0.97 and a value read by
Tesseract at 0.0-with-a-box are different kinds of claim, and the reviewer
should see which they are looking at. `bbox=None` with a value present is a
legitimate state — located nothing, read something elsewhere — and must be
labelled rather than smoothed over.

---

## 6. Override and audit — resolves Open Questions #3 and #4

A reviewer may change any computed status. The record:

```python
@dataclass(frozen=True)
class Override:
    stt: int
    document: str
    from_status: Status     # what the engine computed
    to_status: Status       # what the human decided
    reason: str             # required, free text
    at: str                 # ISO timestamp
    by: str                 # reviewer identity when auth exists; "" until then
```

Overrides layer above computed status and always win, matching the prototype's
`ISSUES` precedence. But unlike the prototype, the computed value is retained —
so `from_status` records what the engine thought.

**That field is the most valuable data this product can generate.** An override
of `ok → no` means the engine was wrong in the dangerous direction. Recorded
from day one, these accumulate into the labelled corpus this project does not
otherwise have, at no marginal cost. An override of `pending → ok` is the
opposite signal: coverage the engine lacked but a human supplied easily.

Who may override, and whether a second confirmation is required, needs a
decision (§8).

---

## 7. The PIT rule is not ours to decide

`LOGIC.md` §16 item 10 flags the withholding threshold as undocumented text with
no legal citation. That caution is correct and this design keeps it.

`compute` for #15 therefore does **not** hardcode a rate. It evaluates only what
the checklist actually asserts: *"Nếu PIT bằng 0, phải xác định có cam kết hoặc
căn cứ miễn/không khấu trừ phù hợp."* Zero PIT without a stated basis is a
finding; a non-zero PIT is reported with its effective rate for a human to judge.

This is not hypothetical. `roster_checks` run against the real July bảng kê
found **14 rows with Gross = exactly 2.000.000, `Bản cam kết` = "không", and
PIT = 0**. The prototype's stated rule is `≥ 2.000.000đ/lần → khấu trừ 10%`, and
`2.000.000 ≥ 2.000.000` holds — so under that rule each row should carry 200.000,
about 2.8M unwithheld on one batch. February is clean.

Either the threshold is exclusive rather than inclusive, or those rows are wrong.
The tool must surface the question and must not answer it.

---

## 8. Tổng hợp tab

The five roster-level criteria the prototype defers. Their STTs were unknown to
it (its Open Question #2); the other checklist file's `Cấp độ` column resolves
them, and they match its `.scope-note` list in order:

| STT | Criterion | Status here |
|---|---|---|
| #20 | Tổng Gross/PIT/Net toàn bảng kê | **closed** — `roster_checks` + `purchase_listing`; resolves on all 8 payment cases |
| #26 | 2 Bảng kê signed by preparer and approver, with seal | `presence`, batch level — human |
| #30 | No CCCD / MST / account shared between CTVs | **built** — `roster_checks` |
| #31 | No duplicate payment (same CTV + amount + period) | **built** — `flag_duplicate_identities` |
| #32 | Document signing dates in a sensible sequence | not built — needs dates across documents |

#19 is **not** one of the five: it is *Phí dịch vụ khớp giữa các chứng từ*, which
the prototype correctly folds into #14's card.

**#20 spans two documents, which is why it looked unbuildable.** None of the
three rosters carries a total row, so an Excel-only check cannot run. The total
is on the last page of the Bảng Kê Thu Mua, and `purchase_listing` reads it
there:

| Submission | Page | Total | Roster Gross sum |
|---|---|---|---|
| July | 8 | 240.305.556 | 240,305,556 ✓ |
| February | 7 | 258.638.890 | 258,638,890 ✓ |

Both reconcile exactly. #20 now reports `ok` on all eight payment cases; the two
PUBGm nghiệm thu submissions have no money columns and no listing, and #20
stays `pending` there, which is correct — it does not apply.

**The total is read twice, and that is not belt-and-braces.** Vietnamese
invoices print every amount in digits and again spelled out. On February's page
7 Tesseract read the `8` in `258.638.890` as `§` — the digit read fails
outright, and the spelled-out amount is the *only* working read. So
`vn_number_words` parses the words, `digit_repairs` proposes bounded OCR
substitutions for the digits, and a repair is accepted only when it reproduces
the words exactly. The words stay the authority; a repair can never invent a
value. When the two reads disagree, #20 abstains and says so rather than
accusing the roster of a mismatch that is really an OCR slip.

### 8.1 Three false-clean results the tab exposed

Wiring these five criteria to real data found three places where "nothing
evaluated" was rendering as "everything fine" — the exact inversion §1.1 exists
to prevent. All three are fixed and regression-tested:

1. **An unreadable roster passed #30.** With no rows or no identity columns the
   check reported *"Không trùng CCCD/MST/tài khoản trên 0 dòng"*. Nothing to
   compare is not nothing colliding; it is now `pending`.
2. **Packets that matched nobody passed #31.** A packet with no `rosterIdentity`
   has no identity to collide with, so a set of unmatched packets was reported
   as clean. Now `pending`, naming how many are unmatched.
3. **#31 trusted a persisted flag.** It read `flags` for
   `duplicate-roster-identity`, but every stored case predates
   `flag_duplicate_identities`, so the July submission — nine CCCDs on two
   packets each — reported clean. The collision is now recomputed from the
   identities, keyed exactly as the pipeline keys it. July reports 9 CTV / 18
   gói; February stays clean.

A criterion whose answer depends on when a case was ingested is not a criterion.

Two further notes from the build:

- **#20 falls back rather than passing.** With no total row and no
  `purchaseTotal` on the case it stays `pending`, names the Bảng Kê Thu Mua, and
  still shows the sum it computed so the number is not lost. `store.set_purchase_total`
  is the hook step 4's parser fills in.
- **The payload reports its own gaps.** `missing` lists the inputs the tab could
  not reach (`rosterRows`, `purchaseTotal`, `packets`), so a pending criterion
  explains itself instead of leaving the reviewer to guess.

Findings render in Acc's own vocabulary, per the workbook's stated principle:
*"Không chỉ báo 'Không khớp'; phải nêu trường sai, giá trị tại từng chứng từ,
chênh lệch và nội dung cần kiểm tra lại."* `roster_checks.Finding` already
carries `criterion / code / message / rows` for exactly this.

---

## 9. Documents

Seven, against the five this codebase models today.

| Document | `EvidenceKind` | Reader |
|---|---|---|
| Bảng kê thanh toán (Excel) | — (roster) | `roster_workbook` |
| CCCD / Passport | `id_front` `id_back` | **IDP** `ID` / `PP` |
| Hợp đồng dịch vụ | `contract` | local OCR; `Document to Text` untested |
| BBNT | `bbnt` | as above |
| Phụ lục / KPI | `appendix` | as above |
| Kết quả tra cứu MST | `pit` (existing) | local OCR |
| **Bảng Kê Thu Mua** (mẫu 02/TNDN) | **new kind needed** | `purchase_listing` — total only, see §9.1 |

**Bảng Kê Thu Mua needs an in-house parser.** IDP's `GET_TABLE` was tested on it
four times — as a 6-page PDF and as upright single-page images, twice each. It
classifies the form confidently once rotation is corrected
(`is_correct_classification` False → True) but returns
`ocr_data: None, schema.table: []` every time. Zero rows.

Our own OCR reads the same page at **288 words, mean confidence 83**, with
money tokens in two tight columns (x≈1860 đơn giá, x≈2100 tổng giá thanh toán)
and identity numbers in one (x≈1000). The total is read reliably from this.
**The rows are not**, and §9.1 records why.

Note this document is **batch-level, not per-packet** — one listing covering all
41 CTVs, which is why #28 concerns a single preparer signature. It sits outside
every packet, in the front matter before the first one:

| Submission | Front matter | Listing total found |
|---|---|---|
| July | pages 1–11 | page 8 (4 pages scanned) |
| February | pages 1–7 | page 7 (1 page scanned) |
| PUBGm | pages 1–32 | none — no listing in this submission |

`pipeline.read_purchase_total` scans that range **backwards**, because the total
is the last thing on the listing.

### 9.1 The rows are not readable at this scan quality

Measured on the July listing's five row pages (41 rows, total 240,305,556):

| Reading | Result |
|---|---|
| Money tokens in the total column, default OCR (300 dpi, psm 3) | 34 tokens, **62%** of the total |
| psm 6 · psm 4 · 400 dpi · 600 dpi · 2× upscale | 49–61% — every one **worse** |
| Exact-matching the 41 known roster amounts against all tokens | 32/41, **78%** |

The shortfall is digit-level corruption, not missed detection. The nine
unmatched roster amounts have near-twins among the unclaimed tokens —
`7.777.778` read as `1.777.778`, `2.777.778` and `1.771.718`; `8.888.889` as
`8.888.880`, `8.885.880` and `8.888.850`. Recovering those needs
digit→digit substitution, which would let almost any token match almost any
amount. That is the invention this design refuses.

**So #14's third column, #27 and #28 stay blocked**, and the honest reason is
input quality rather than missing code. A fuzzy matcher would raise 78% to
roughly 88% while flagging nine non-problems out of forty-one — a tool the
reviewer would learn to ignore.

Two things make this an acceptable place to stop:

- #20 already carries the aggregate guarantee. The printed total equals the
  roster sum **exactly**, so the listing's rows and the roster's rows agree in
  total. Per-row matching would only add detection of offsetting errors, and
  #17 already checks each row's own arithmetic.
- The unblock is better input, and it is already on the list: Acc's original
  files rather than a scan of a print, or a table-capable model. Both raise the
  ceiling for every reader, not just this one.

---

## 10. Out of scope

- **Signature or seal authenticity**, signer authority, fraud. `presence`
  navigates; it never concludes.
- **A hardcoded PIT rate.** §7.
- **Live MST lookup.** #06 reads a supplied artefact.
- **Approve / reject.** The reviewer flags and sends back; the tool has never
  had an approve action and does not gain one here.
- **Batch-level packet navigation changes.** Out of this spec.

---

## 11. Open questions

1. **PIT threshold** (§7) — inclusive or exclusive at 2.000.000, and the legal
   citation. 14 real rows depend on the answer. Carries forward the prototype's
   own Open Question #7.
2. **Who may override**, and whether `ok → no` needs a second confirmation.
   Prototype Open Questions #3 and #4.
3. **`presence` default.** This spec says `rv`. The alternative is `pending`,
   which reads as "not looked at" rather than "needs you". `rv` is proposed
   because six criteria would otherwise sit indistinguishable from unevaluated
   ones.
4. **`Document to Text` code** — unknown `doc_type` values return HTTP 500, so
   it cannot be found by guessing. One dropdown switch in the playground's API
   tab settles it, and it decides whether the three contract-family documents
   get a better reader.
5. **#32 date sequencing** — needs signing dates extracted from four document
   types. Deferred until the contract-family reader is settled.
6. **Auth.** Overrides want an author. Prototype Open Question #1.

---

## 12. Order of work

1. ~~**Criteria registry + status model + aggregation.**~~ **Done** (`server/criteria.py`).
   No new extraction; wires the 25 criteria to what the pipeline already
   produces and computes the summary the prototype hand-types.
2. ~~**Tổng hợp tab.**~~ **Done** — `server/summary_criteria.py`,
   `GET /api/cases/{cid}/summary`, `src/components/SummaryTab.tsx`. It was less
   "mostly presentation" than this spec assumed: building the tab surfaced three
   false-clean results the per-criterion tests had not (see §8).
3. ~~**`compare` and `compute` evaluators.**~~ **Done** — `compare_values.py`,
   `evaluate.py`, `GET /api/cases/{cid}/packets/{i}/criteria`,
   `src/components/CriteriaMatrix.tsx`. The matrix is computed. §3.6 records what
   it found on the real submission, which is not what this spec expected.
4. ~~**Bảng Kê Thu Mua parser**, checksum-gated.~~ **Total done** —
   `purchase_listing` + `vn_number_words`, closing #20 on all eight payment
   cases. **Rows not done and not attempted**: §9.1 measures the ceiling at
   62% extraction / 78% corroboration, so #14's third column, #27 and #28 stay
   blocked on better input rather than on code.
5. **Override and audit.** Needs the auth decision first.
