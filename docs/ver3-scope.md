# Ver 3 — scope notes

**Started 2026-08-28.** Notes only; nothing here is designed or agreed yet. Ver 3 step 1 (the
CCCD review step) has shipped — see `docs/superpowers/specs/2026-08-27-ver3-cccd-review-step-design.md`.

---

## 1. A new input: one workbook that replaces two, and carries three kinds of image

**The sample:** `Nghiem thu CTV - PUBGm Esports -AGQ2026.xlsx` (18 MB), alongside
`FA-PM260706029.pdf` (178 pages). Measured, not assumed:

| sheet | people | images | where the images sit |
|---|---|---|---|
| `CTV` | 25 | 0 | the bảng kê itself — header on **row 5**, data from row 7 |
| `CCCD` | 25 | **75** | col D ×24, col E ×24, col G ×25 |
| `MST` | 25 | **25** | cols C–D |

### What this changes

**It collapses two of today's three inputs into one.** Today `POST /api/cases` takes `pdf`,
`roster` and `cccd` separately. Here the `CTV` sheet *is* the roster and the `CCCD` sheet
carries the card images. A submission in this format has two files, not three.

**It introduces two evidence types the tool has never had.** The images are not all cards:

- `CCCD` col D / col E — card front and back, what we handle today
- `CCCD` col G, under the **STK** heading — **screenshots of the bank account**
- `MST` sheet — **screenshots of the tax-authority lookup**

**Today's extractor would mangle it.** `cccd_workbook` pulls *every* image out of the workbook
and pairs front/back by anchor proximity. Given this file it would treat bank screenshots and
tax screenshots as card candidates, and would happily pair a card front in col E with a bank
screenshot in col G — they are two columns apart. The extractor has to become **column-aware**:
read the header row, learn which column holds which kind of image, and never pair across kinds.
Proximity pairing was a reasonable guess when the workbook was cards only; it is wrong now.

### The part worth getting excited about

Two of the criteria that today produce nothing become answerable, because the submitter is now
supplying the evidence:

- **#6 Trạng thái MST** — currently 39 `rv` per case, because confirming it "needs the tax
  website". The `MST` sheet is a screenshot *of that website*, one per person.
- **#8 Thông tin ngân hàng** — currently every cell `pending`, nothing extracted. The `STK`
  column gives account + bank as text, and col G gives a screenshot to check it against.

A third becomes real rather than nominal: **#4 Giới tính** is dismissed in
`criteria-reliability.md` as checking "one Excel column and nothing else" — the card front
carries giới tính, so it could become a genuine two-source comparison.

That is three of the seven "not built" / "always routes to a person" criteria, unlocked by an
input change rather than by better OCR.

### Columns the bảng kê now carries that we ignore

`Giới tính`, `Ngân hàng`, `Thời gian làm việc`, `Công việc`, `SĐT`, and a header block with
`Mã eform plan` / `Mã eform thanh toán`. The eform codes look like the natural join back to the
payment request itself — worth checking whether they appear on the PDF's cover page.

### Open questions

- Do both formats need to be supported at once, or is this replacing the old one? Detecting
  sheet names (`CTV` / `CCCD` / `MST`) is a cheap discriminator if both must live.
- The header row is row 5 here, not row 1. `roster_checks.locate_columns` already searches for
  it — confirm it copes with this layout before assuming it does.
- 24 fronts and 24 backs for 25 people: one person is missing a card side in the source file.
  What should that produce — a missing-document finding, or silence?
- Two stray images in `CCCD` col C and seven in `MST` col C. Unknown what they are.

---

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
