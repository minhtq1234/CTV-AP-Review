# Ver 3 — scope notes

**Started 2026-08-28.** Notes only; nothing here is designed or agreed yet. Ver 3 step 1 (the
CCCD review step) has shipped — see `docs/superpowers/specs/2026-08-27-ver3-cccd-review-step-design.md`.

---

## 1. Another document-input template — the tool assumes there is only one

**Corrected after measuring.** This is not a new input format to migrate to; it is a *second
template*, and submissions arrive in both. The July batch (Danh Tướng 3Q) sends `roster.xlsx`
plus a separate `cccd.xlsx`. The PUBGm Esports batch sends **one workbook with three sheets**.
Both are legitimate. The tool currently assumes the July shape.

**The sample:** `Nghiem thu CTV - PUBGm Esports -AGQ2026.xlsx` (18 MB) with
`FA-PM260706029.pdf` (178 pages — a submission the tool has already processed, as 25 packets).

| sheet | people | images | columns the images sit in |
|---|---|---|---|
| `CTV` | 25 | 0 | the bảng kê — header on **row 6**, 13 columns mapped |
| `CCCD` | 25 | **75** | D ×24 front · E ×24 back · **G ×25 bank-account screenshots** |
| `MST` | 25 | **25** | **tax-lookup screenshots** |

### The good news: layout variance is already handled

`roster_checks.locate_columns` searches for the header row and maps by column name, so it reads
the new template unaided — header at row 6, and it recovers **account, bank, cccd, commitment,
dob, gender, gross, mst, name, net, period, pit, stt**, 25 people. All three sheets parse. No
work needed there, and cross-sheet checking (see §3) is nearly free as a result.

### The bad news: which sheet gets read is decided by the submitter's mouse

`roster_workbook.load_roster_rows` takes **`workbook.active`** — the tab that happened to be
selected when the file was last saved. Measured on this file: **`active` is `CCCD`, not `CTV`.**

Fed in today, that does not fail. It parses 25 people carrying only name, CCCD and STT, and
produces a case in which every money and identity criterion has nothing to compare against —
silently, with no error anywhere. The July template has a single sheet, so `active` was always
correct and the assumption was invisible until now.

**Fix direction:** choose the roster sheet by what it contains, not by which tab is open — the
sheet whose header maps the most required columns wins, with the others available as companions.
That also removes the need to name sheets `CTV`/`CCCD`/`MST`, which the next template will spell
differently anyway.

### The images are three populations, not one

The extractor pulls *every* image out of the workbook and pairs front/back by anchor proximity.
Given this file it would treat bank and tax screenshots as card candidates, and would pair a card
front in col E with a bank screenshot in col G — two columns apart. It has to become
**column-aware**: read the header, learn which column holds which kind, never pair across kinds.
Proximity pairing was reasonable when the workbook was cards only; it is wrong now.

### The part worth getting excited about

Two criteria that produce nothing today become answerable, because this template supplies the
evidence:

- **#6 Trạng thái MST** — currently 39 `rv` per case because confirming it "needs the tax
  website". The `MST` sheet is a screenshot *of that website*, one per person.
- **#8 Thông tin ngân hàng** — currently every cell `pending`. The `STK` column gives account and
  bank as text; col G gives a screenshot to check it against.

And **#4 Giới tính**, dismissed in `criteria-reliability.md` as checking "one Excel column and
nothing else", could become a real comparison — the card front carries giới tính.

Three of the seven unbuilt or always-routed criteria, unlocked by an input template rather than
by better OCR.

### Template differences that change behaviour

- **`pit` is filled on only 8 of 25 rows here**, against every row in July. Criterion #15 produces
  14 of 20 rejections on the July batch; a template that leaves PIT blank will not behave the same
  way, and `commitment` is filled on all 25 rows, so the rule's other half is present. Worth
  measuring before assuming #15 transfers.
- 24 fronts and 24 backs for 25 people — one card side missing in the source.
- Two stray images in `CCCD` col C, seven in `MST` col C. Unidentified.
- The header block carries `Mã eform plan` and `Mã eform thanh toán`, which look like the join
  back to the payment request. Worth checking whether they appear on the PDF cover.

### Decision: read both templates, do not ask users to transform their files

Two templates are known today. The question raised was whether to build a second input path or
to give submitters a converter / canonical template to fill in. **Read them. Do not transform.**

**The layout is self-describing, so this is inference, not an adapter.** `D1:E1` on the CCCD
sheet is a *merged* cell labelled `Hình CCCD` — the header itself says columns D and E are the
two card sides. `Hình Ảnh` sits beside `STK`; on the MST sheet `Hình Ảnh` sits beside `MST`. The
same header-search that already maps roster columns can map image columns.

**We have already proved the approach on the harder half.** `locate_columns` reads both templates
with no per-template code — header on row 1 in one, row 6 in the other, 13 columns recovered from
a sheet it had never seen. Nobody wrote an adapter for that; they wrote a reader that looks at
headers. The images are not harder.

Why not a transform, in order of weight:

1. **Transcription is the failure class this tool exists to catch.** Any human transform — retyping
   into a canonical template, or correcting what a converter got wrong — is a fresh chance for one
   digit of a CCCD or an account number to change. Packet 34 is that exact shape: `001100000151`
   for `001100000101`, one digit, found only because a criterion compared it against the bảng kê.
   Adding a copy step upstream manufactures the defect the downstream is built to detect.
2. **The original stops being the evidence.** This is an audit tool; the artifact checked should be
   the artifact submitted. A converter that silently mis-maps a column hands the tool a clean-looking
   file with no way to know — the same shape as the `workbook.active` bug above, but outside the
   codebase where it cannot be measured.
3. **The submitters will not do it reliably.** These are product teams attaching files to a payment
   request. The evidence is in this very workbook: the same card pasted twice on two sheets, 24
   fronts for 25 people, stray images in column C. A process that produces those will produce
   canonical templates with the same errors plus transcription ones.
4. **A canonical template still versions.** You would end up maintaining the template *and* readers
   for its old versions — the thing the transform was meant to avoid.

**Transformation does belong in this design — one layer inward.** Several readers, one canonical
internal shape. That is the normalisation layer we would build regardless; it just runs inside the
tool, on the file the submitter actually sent, instead of on a copy someone made by hand.

### What that means concretely

- **Pick the roster sheet by content, not by `workbook.active`** — the sheet whose header maps the
  most required columns. Not a template feature; removing a wrong assumption, and it fixes both
  known templates plus most unknown ones.
- **Map image columns by header**, the way roster columns are mapped: a merged `Hình CCCD` spanning
  two columns means front and back; `Hình Ảnh` next to `STK` means a bank screenshot; on a sheet
  keyed by MST it means a tax-lookup screenshot.
- **Keep proximity pairing as the fallback**, used only when no image headers are found, so the
  July `cccd.xlsx` (which has no such headers) keeps working unchanged.

### The risk, and what answers it

Inference can be confidently wrong and silent — precisely the bug found above. So it has to be
**shown**. The bảng kê pre-flight in §3 is where the tool states what it inferred:

> bảng kê read from sheet `CTV` · 25 people · 24 card fronts in column D, 24 backs in column E ·
> 25 bank screenshots under `STK` · 25 tax screenshots on sheet `MST`

A reviewer confirms that in seconds, before a 51-minute run commits to it. That buys inference's
flexibility with a declaration's auditability — and it is why notes 1 and 3 are really one piece
of work, not two.

### Settled

- **Two templates, and no more expected for now.** Scope is exactly the July pair
  (`roster.xlsx` + `cccd.xlsx`) and the PUBGm combined workbook. The inference approach still
  stands at two, and not because a third is anticipated: the roster half already reads both with
  no work at all, the sheet-selection fix is required regardless because it is a live bug, and
  mapping image columns by header costs about the same as hard-coding them for two files. A third
  template would then be free rather than another rebuild — but that is a side effect, not the
  justification.
- **`Mã eform` is not checked.** The header block carries `Mã eform plan` and `Mã eform thanh
  toán`, and they look like the join back to the payment request, but nothing compares them
  against the PDF cover and nothing should. Read them if they are free to read; do not build a
  criterion on them.

## 2. Clicking a status cell opens its document

**Ask:** in the 25-criteria view and the Dạng bảng view, clicking a ✓ / ✗ / ? / ! opens the
document that cell refers to, in a popup. Full document, **no autofocus** on the value.

**Most of this is built.** `PacketDocsDialog` (shipped 2026-08-28) already opens a person's
documents in a modal over the packet list, reusing `EvidenceViewer` read-only. The work is
opening it on a *specific* document, from a status cell rather than from the `CHỨNG TỪ` cell.

### The mapping that has to exist

The matrix renders eight columns (`criteria.py:35-42`), and they are **criteria column names, not
manifest documents** — there is no direct identity between them today, so this map is the one new
piece:

| column | opens |
|---|---|
| `Hợp đồng` | kind `contract` |
| `BBNT` | kind `bbnt` |
| `Phụ lục/KPI` | kind `appendix` |
| `Cam kết PIT` | kind `commitment` |
| `Website tra cứu MST` | kind **`pit`** — the column names MST, the kind is `pit`; easy to get wrong |
| `CCCD/Passport` | kinds `id_front` **and** `id_back` |
| `Excel` | nothing |
| `Bảng Kê Thu Mua` | nothing per person |

### Decided

1. **`Excel` cell: do nothing.** It is the reference value, not a document.
2. **`Bảng Kê Thu Mua` cell: navigate to the Tổng hợp tab.** It is a roster-level document and the
   criterion's own note already says to check it there.
3. **`CCCD/Passport` opens the front**, with the back reachable through the viewer's existing tabs.
   No decision needed at click time.
4. **"No autofocus" applies to this popup only.** The packet-review screen keeps its current
   behaviour, where selecting a field highlights the value's bounding box on the scan — that is
   useful there. Here it would be wrong: a `pending` or `missing` cell has no box to focus, and the
   viewer would open on a page with nothing marked.

### Defined, not decisions

- A `na` cell and a cell whose document is not in this person's file — only 20 of 41 have a
  `Phụ lục` — do nothing on click. The reason is already in the cell's note; the click should not
  open an empty viewer to say so.

## 3. Bảng kê validation lives in the Excel column, not in a new screen

**Decided, replacing the pre-flight sketch below.** The Excel column of the matrix already *is*
per-row bảng kê validation. Measured on one person today, it asserts:

| criterion | what the Excel cell already says |
|---|---|
| #2 | `đúng định dạng 12 chữ số hoặc hộ chiếu 8 ký tự` — format |
| #3 | `đúng định dạng text dd/mm/yyyy` — format |
| #5 | `đúng định dạng 10 chữ số hoặc 12 chữ số` — format |
| #16 | `Net dương: 8,000,000` — arithmetic |
| #17 | `Tính lại đúng: 8,888,889 − 888,889 = 8,000,000` — arithmetic |
| #8–#11 | `Bảng kê không có giá trị cho tiêu chí này` — presence |
| #15 | PIT — explicitly not auto-checked |

Four of the six checks a validation pass would perform already run here. So the work is **filling
gaps in an existing column**, not building a screen: the PIT rule (#15), and whatever the second
template needs now that it fills different columns.

This also resolves the earlier note about moving #16, #17 and #4 out of the per-packet matrix.
They do not need to move — the Excel column is already where their roster-side answer is shown.

### What a per-person column structurally cannot show

Two classes of problem do not belong to any one row, and both already have a home in **Tổng hợp**,
which computes roster-spanning checks "from the roster as uploaded plus the packets'
duplicate-identity flags" (`app.py:367`):

- **cross-row** — two people sharing a CCCD or an MST, which makes packet→person matching ambiguous
- **cross-sheet**, once the second template lands — `CTV`, `CCCD` and `MST` listing different
  numbers for the same person

### The one real gap left

**A wrong-sheet read is indistinguishable from a normal absence.** If the tool reads the `CCCD`
sheet as the bảng kê — which `workbook.active` makes possible today, see §1 — then MST, gross and
net have no column, and every Excel cell reports `Bảng kê không có giá trị cho tiêu chí này`. That
is character-for-character what a legitimately unfilled column reports. A reviewer cannot tell a
catastrophe from a normal case, and only finds out after a 51-minute run.

Minimal answer, and it is small: at upload, after choosing the roster sheet by content (§1),
check it has the columns without which nothing works — name, CCCD, and at least one money column.
If it does not, refuse the upload and say which sheet was read and what was missing. That is a
guard against reading the wrong thing, not the general-purpose validation gate sketched below —
per-row validation stays in the Excel column where it already lives.

### Deliberately not doing

- A separate validation screen or a standalone "check my bảng kê" upload.
- A fatal-versus-warning severity scheme. Without a gate there is nothing to gate, and the Excel
  column already expresses severity through the same statuses as every other cell.
- Moving #16, #17, #4 or #15 out of the matrix.

---

## 4. Data leaving the machine: what is approved

Recorded here because it is a standing decision, not a task, and because everywhere else this
project is deliberate about it — `server/data/` is gitignored, and the plans forbid a real
contractor's details in a test fixture on the grounds that fixtures reach a public repository.

**Approved, 2026-08-28, by the project owner (minhtq4):** sending **contract page text** to
GreenNode's MaaS inference endpoint
(`https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1/chat/completions`), authenticated with the
existing `GREENNODE_API_KEY`, for the semantic reading of criteria #8, #9, #10, #11 and #13.

The disclosure this widens, stated plainly so nobody has to reconstruct it later:

| | before | now approved |
|---|---|---|
| what is sent | a cropped ID card image | full text of the contract pages being read |
| what that contains | the card's own fields | name, CCCD, address, bank account, amounts, signature block |
| to whom | GreenNode IDP | GreenNode MaaS — same vendor, same tenancy, same key |

The question was raised in review of `docs/superpowers/plans/2026-08-28-semantic-extraction.md`,
which had wrongly asserted the existing card-reader approval already covered it. It did not; this
entry is the approval.

**Still not approved, and not to be assumed from the above:**

- any other vendor or endpoint — this covers GreenNode's tenancy and nothing else
- sending **page images** rather than text
- sending the bảng kê, the CCCD sheet, or card images to the MaaS endpoint
- sending anything at all when the credentials are unset: absent keys must leave the cells
  `pending`, exactly as the card reader behaves today

---

## Appendix — the original pre-flight sketch, superseded

Kept because the reasoning about *what* to check is still the checklist for filling the Excel
column's gaps, even though the *where* was wrong.

**The ask:** if the bảng kê is wrong, nothing else matters, so check it before doing anything else.

**Why this is right, in numbers.** A full pass on the July submission measured **51 minutes** —
13 reading pages, 36 matching cards. Every one of those minutes is spent comparing documents
against the bảng kê. If the bảng kê cannot be parsed, or has two people sharing a CCCD, the tool
spends fifty minutes producing comparisons against a reference that was never sound. Today that
failure surfaces late and diffusely — as 41 packets reading "chưa khớp bảng kê" — rather than as
"row 14 has a 9-digit CCCD".

### What a validation pass should actually check

Roughly in order of how cheap and how fatal each is:

1. **Structure** — is there a header row, and are the required columns present? (Họ và tên,
   CCCD/PP, MST, số tài khoản, ngày sinh, and the money columns.) Fatal: nothing downstream works.
2. **Per-row format** — CCCD 12 digits (or 9 for an old CMND), MST 10 or 13, account numeric,
   date parseable, giới tính in a known set. Fatal per row, not per file.
3. **Uniqueness** — no two rows sharing a CCCD or an MST. Fatal: packet→person matching becomes
   ambiguous, and `summary.duplicate_identities` already counts this after the fact.
4. **Arithmetic** — Gross − PIT = Net per row; PIT against the withholding threshold and the cam
   kết. This is exactly what criteria #16, #17 and #15 do today.
5. **Cross-sheet agreement** — new, and only possible with the workbook above: `CTV`, `CCCD` and
   `MST` each list name + number for the same 25 people. If the CCCD sheet says a different number
   for someone than the CTV sheet does, that is an error in the submission, findable in seconds,
   with no PDF and no OCR involved.
6. **Completeness** — does every person have a card image and an MST screenshot? A count, not a read.

### The structural insight

**Three of the 25 criteria do not belong in the per-packet matrix at all.** `criteria-reliability.md`
already says #16 Net, #17 Gross − PIT = Net and #4 Giới tính "compare the roster against itself —
they are not document verification", and that all three pass 41/41 every time. They are bảng kê
validation wearing a per-packet costume. Moving them into this pass would:

- remove three always-green rows from every packet's matrix, on every case
- put the failure where it is actionable — one bad row, named once, instead of the same finding
  repeated under one person
- make the per-packet matrix honestly about *documents versus the bảng kê*, which is what it claims to be

#15 PIT is the interesting boundary case: it is a rule about the bảng kê's own numbers, so it
belongs here by the same logic — but it is also the criterion producing 14 of 20 rejections, so
moving it changes what the packet list shows. Worth deciding deliberately rather than by category.

### Where it runs

Cheap enough to run as a **pre-flight**: parse the workbook, report, and refuse to start the
50-minute pass if it fails. Two things follow from that:

- It should be runnable **on its own**, before any PDF exists. The AP team could check a bảng kê
  the moment it arrives and send it back the same day, rather than after a processing run.
- It needs a **severity split**. A missing SĐT should not block a submission; a duplicate CCCD
  should. Get that list agreed before building, because "validation failed" with no way forward
  is worse than the current late failure.

### Open questions

- Can a reviewer override and process anyway? Probably yes, explicitly — there will be a real
  submission with one bad row that someone needs processed today.
- Does the Tổng hợp tab become the home for this, or is it a separate screen before the case
  exists? Tổng hợp already holds the five roster-level criteria.
- Does the eform code in the header get checked against the PDF cover, and is that fatal?
