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
   digit of a CCCD or an account number to change. Packet 34 is that exact shape: `070198011354`
   for `079198011354`, one digit, found only because a criterion compared it against the bảng kê.
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

### Still open

- How many templates exist beyond these two, and do they come from the same team each period?
- Does the `Mã eform` header block appear on the PDF cover, and should it be checked against it?

## 2. Clicking a status cell should open the document

**Ask:** in the 25-criteria view and the Dạng bảng view, clicking a ✓ / ✗ / ? / ! opens the
document that cell refers to, in a popup. Full document, **no autofocus** on the value.

**Most of this already exists.** `PacketDocsDialog` (shipped today) opens a packet's documents
in a modal over the list, reusing `EvidenceViewer` read-only. The work is to open it *on a
specific document* rather than the first one, from a cell rather than from the `CHỨNG TỪ` cell.

Notes for whoever picks it up:

- A cell already knows its document — `Cell.document` is what the matrix renders its columns from.
  The mapping from that to a manifest `docId` is the only lookup needed.
- "No autofocus" is a deliberate reversal of the reviewer's existing behaviour, where selecting a
  field scrolls and highlights the value's bounding box. That is the right call for a cell that is
  `pending` or `missing` — there is no box to focus, and today's viewer would sit at the top of a
  page with nothing marked. Worth confirming the reviewer still *wants* the highlight when opening
  from the packet-review screen, where it does help.
- The Excel column is a cell too. Clicking it has no document to show — it should either do
  nothing or show the bảng kê row. Decide before building.

---

## 3. Validate the bảng kê first — thinking it through

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
