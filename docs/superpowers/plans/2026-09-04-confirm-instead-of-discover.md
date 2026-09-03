# Confirm Instead of Discover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #01 Họ và tên stops answering `?` on documents that plainly carry the name, and #05 MST and
#07 Số tài khoản stop reporting `Không khớp` when the paperwork is right and the reader misread it.

**Architecture:** Ask a different question. The bảng kê already states what every value should be, so
a criterion does not have to *discover* the value on the page — it can *confirm* the expected one is
there. Confirming is a search, and search is both easier and safer than extraction.

**Tech Stack:** Python 3.11+ · pytest. No model, no network, no vendor.

---

## Why this exists

Measured on case `935e37e5`, packet 0. The contract and BBNT are perfectly legible — the tool pulled
the CCCD at 0.80/0.84 and the date of birth at 0.93/0.96 off those same pages. But:

- **#01 answered `?` on both.** The name field is the only one with `"patterns": []`. A number
  announces itself by shape; a name does not. The contractor's name looks exactly like the
  name of VNG's own signatory, printed two lines above it. So the extractor requires a label saying whose name it
  is, and on this contract **there is none on any of its four pages**. The name sits on a bare line.
- **#05 read `001100000004` where the bảng kê says `001100000001`** — one digit, at 0.84 confidence.
  That is a `Không khớp` a reviewer must adjudicate, caused by a misread rather than bad paperwork.

Both are the same shape of problem: the tool is being asked to work out the answer from scratch when
the answer is already known.

## What was measured before writing this

**Names — searching for the expected name works, and discriminates.**

| | |
|---|---|
| expected name found on the document | **1.00 on all 9** document-packet pairs of case `935e37e5` |
| highest score between two *different* people, across all **79** distinct names on disk | **0.81** |
| pairs of different people scoring ≥ 0.90 | **0** |

The hardest real cases sit safely below: the closest real pair on disk scores 0.80 — two people sharing
a surname and middle name, both in one submission. A threshold at **0.90** separates cleanly.

**Numbers — a free-floating search would confirm itself, every time.**

> Across **564 roster rows on disk, `cccd == mst` in 564 of them — 100%.**

A Vietnamese personal tax code is the citizen's ID number. So searching a page for the expected MST
would match the CCCD occurrence and report a confirmation that means nothing. **A number search must
be anchored to its own label.** The labels already exist and are distinct
(`server/ocr_extract.py` FIELD_SPECS):

| field | anchors |
|---|---|
| `cccd` | `can cuoc`, `so cccd`, `cccd so`, … |
| `mst` | `msttncn`, `ma so thue thu nhap ca nhan`, `mst tncn`, … |
| `tk` | `so tai khoan`, `tk so` |

---

## Two mechanisms, not one

Do not build one generic "search for the expected value". Names and numbers fail differently and the
safe answer differs.

**Names (#01) — the value cannot be discovered at all.** No label, no shape. Search the whole
document for the expected name. Safe because a specific name cannot collide: VNG's signatory scores
nowhere near the contractor's.

**Numbers (#05, #07) — the value is found and sometimes misread.** The label is already located and
the digits already read. Search only *at that label* and only to answer one question: **when the read
disagrees with the bảng kê, is the expected value actually printed there?** If yes, the reader
misread and the cell should say so. If no, the paperwork really does disagree.

**Never let a number search upgrade a cell to `Đạt` on its own.** It changes what a `Không khớp`
*means*; it does not overrule the reader. Getting this backwards would let the tool confirm whatever
the bảng kê claims, which is the opposite of an audit.

---

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

- **`pytest` must run with `server/` as the working directory.**
- Baseline: establish your own before changing anything and compare against it.
- **Word boxes are discarded after ingest** — the manifest keeps only `{src, width, height}` per
  page. Anything that needs to point at a place on a page must record it during the read, exactly as
  `signature_anchors` and `semantic_read` already do.
- **Never put a real contractor's details in a test.** Use the synthetic series
  (`001100000001`, `NGUYEN VAN MOT`). A recent commit scrubbed real identities out of the fixtures;
  do not reintroduce any.
- **These changes need a re-ingest to show on an existing case.**

---

## File Structure

| File | Responsibility |
|---|---|
| `server/confirm_expected.py` **(create)** | Pure: does an expected value appear, and where. |
| `server/confirm_expected_test.py` **(create)** | Its tests. |
| `server/ocr_extract.py` **(modify)** | Record name candidates and label neighbourhoods at read time. |
| `server/evaluate.py` **(modify)** | Use them for #01, and to explain #05/#07 disagreements. |

---

## Task 1: Does this expected value appear?

**Files:**
- Create: `server/confirm_expected.py`
- Create: `server/confirm_expected_test.py`

- [ ] **Step 1: Write the failing test**

```python
# server/confirm_expected_test.py
from confirm_expected import confirm_name


def test_the_expected_name_is_found_when_it_is_on_the_page():
    words = "HỢP ĐỒNG DỊCH VỤ Bà TRAN THI HAI Trưởng Phòng NGUYEN VAN MOT 01/01/1990".split()
    hit = confirm_name("NGUYEN VAN MOT", words)
    assert hit is not None
    assert hit.score >= 0.90


def test_another_persons_name_on_the_same_page_is_not_a_match():
    """The whole reason #01 refuses to answer today: a contract carries VNG's
    signatory as well as the contractor. Confirming a SPECIFIC name is what
    makes this safe where discovering one is not."""
    words = "HỢP ĐỒNG DỊCH VỤ Bà TRAN THI HAI Trưởng Phòng NGUYEN VAN MOT".split()
    assert confirm_name("TRAN THI HAI", words) is None


def test_two_people_sharing_a_surname_and_middle_name_do_not_collide():
    """Measured: the closest real pair on disk scores 0.80 -- two people
    sharing a surname and middle name, both in one submission. The threshold
    has to sit above that and below a real hit."""
    words = "Bên Cung Ứng NGUYEN VAN MOT ký tên".split()
    assert confirm_name("NGUYEN VAN HAI", words) is None


def test_accents_and_case_do_not_matter():
    """OCR drops diacritics routinely."""
    words = "ben cung ung NGUYEN VAN MOT".split()
    assert confirm_name("Nguyễn Văn Một", words) is not None


def test_a_missing_expected_value_confirms_nothing():
    """No roster match means nothing to search for. It must not fall back to
    'find any name', which is the discovery problem this avoids."""
    assert confirm_name("", "NGUYEN VAN MOT".split()) is None
```

- [ ] **Step 2: Run it red**

```bash
cd server && python3 -m pytest confirm_expected_test.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'confirm_expected'`.

- [ ] **Step 3: Implement `confirm_name`**

Slide a window of the expected name's word-length across the page's words, fold both sides with
`ocr_extract.norm`, score with `difflib.SequenceMatcher`, and return the best hit at or above
**0.90** with its word span — `None` otherwise.

**Reuse, do not reimplement.** `norm`, `group_lines` and `union_bbox` are in `ocr_extract`;
`semantic_read.locate_quote` already does whole-document fuzzy location and was measured at 100% on
verbatim text. Read it before writing a second matcher, and say in your report whether you reused it
or why you could not.

- [ ] **Step 4: Add `confirm_at_label`, for numbers**

Same idea, deliberately narrower: given the words, a set of label anchors, and an expected value,
look **only within the label's neighbourhood**. Returns whether the expected value is printed there.

Write a test that would fail without the label restriction:

```python
def test_an_mst_is_not_confirmed_by_the_cccd_printed_elsewhere():
    """Measured on 564 roster rows: cccd == mst in 100% of them, because a
    Vietnamese personal tax code IS the citizen's ID number. A free-floating
    search for the expected MST would match the CCCD occurrence and confirm
    itself -- which is why this one is anchored to its own label."""
    words = "CCCD số : 001100000001 ... MSTTNCN : 001100000009".split()
    assert confirm_at_label("001100000001", words, ("msttncn",)) is None
```

- [ ] **Step 5: Run green and commit**

```bash
cd server && python3 -m pytest confirm_expected_test.py -q
git add server/confirm_expected.py server/confirm_expected_test.py
git commit -m "feat(criteria): confirm an expected value on a page, by name or at a label"
```

---

## Task 2: Answer #01 from the bảng kê's own name

**Files:**
- Modify: `server/ocr_extract.py`
- Modify: `server/evaluate.py`
- Modify: their tests

- [ ] **Step 1: The ordering problem, and why it forces a recorded neighbourhood**

`ocr_packet` runs **before** `match_roster`, so at read time the packet's person is not yet known and
there is no expected name to search for. And the words are gone afterwards.

So record, at read time, the **candidate name lines** — the lines near each located CCCD label, with
their boxes — into the document's manifest entry. After matching, `fill_expected` (or evaluation)
compares the now-known roster name against those candidates.

**Read `pipeline.py` around `ocr_packet` and `fill_expected` and confirm this ordering yourself
before building on it.** If it differs, follow the code and say so.

Keep it small: a handful of short lines with boxes, not the page's words. The manifest is read on
every request.

- [ ] **Step 2: Write the failing test, implement, run green**

A packet whose contract carries `NGUYEN VAN MOT` on a bare line near the CCCD label, whose roster row
says `NGUYEN VAN MOT`, must produce an `ok` cell for #01 on that document **with a bbox**. One whose
roster row says `TRAN THI HAI` must not.

- [ ] **Step 3: Measure it, do not assume it**

Re-ingest a real case and report #01's cell states across every packet, before and after. On case
`935e37e5` the expected outcome is `?` → `ok` on contract and BBNT for all five packets; on the
41-packet case, report what actually happens. **Report the number, including any packet where the
name is found on a document it should not be.**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(criteria): confirm the bảng kê's name on the document, rather than discovering one"
```

---

## Task 3: Tell a misread from a mismatch, for #05 and #07

**Files:**
- Modify: `server/ocr_extract.py`, `server/evaluate.py`, their tests

- [ ] **Step 1: Record the label neighbourhood at read time**

Where a number field's anchor is located, record the text found at it — whether or not the digits
parsed. That is what lets evaluation ask, later, "was the expected value actually printed here?"

- [ ] **Step 2: Write the failing test**

```python
def test_a_one_digit_misread_is_reported_as_a_misread_not_a_mismatch():
    """Measured on case 935e37e5 packet 0: the BBNT's MST read 001100000004
    against a bảng kê saying ...113, one digit, at 0.84 confidence. Today that
    is an indistinguishable `Không khớp`; four of eight hand-checked
    disagreements have turned out to be exactly this."""
    # a packet whose bbnt label neighbourhood contains the expected digits
    # while the parsed value differs by one character
    cell = evaluate_cell(5, "BBNT", packet, roster)
    assert cell.status is Status.REVIEW          # not NO
    assert "đọc sai" in cell.note or "misread" in cell.note.lower()


def test_a_genuine_disagreement_is_still_a_mismatch():
    """The point of the tool. If the expected value is NOT printed at that
    label, the paperwork really does disagree and must still say so."""
    cell = evaluate_cell(5, "BBNT", packet_with_a_different_account, roster)
    assert cell.status is Status.MISMATCH
```

- [ ] **Step 3: Implement, and mind the direction**

A confirmed-at-label expected value downgrades `no` → `rv` with a note naming the misread. It must
**never** upgrade anything to `ok`: the tool is not entitled to conclude the paperwork is right
because the bảng kê says so. Say in your report that you checked this.

- [ ] **Step 4: Measure the effect on real cases**

Report, across a real case: how many #05 and #07 cells were `no` before, how many after, and how many
moved to `rv`. A large movement is the point; a movement to `ok` is a defect.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(criteria): separate a misread number from a real disagreement"
```

---

## What this deliberately does not do

- It does **not** answer #01 for a packet with no roster match — there is nothing to search for, and
  falling back to "find any name" is the discovery problem this exists to avoid.
- It does **not** make the tool read a name independently. A `✓` on #01 means *the bảng kê's name is
  printed on this document*, which is what the criterion asks. It would not satisfy a criterion
  needing the name read on its own.
- It does **not** replace the semantic layer. #08, #09, #10, #11 and #13 have no expected value on
  the bảng kê to confirm — that is exactly why they need reading rather than searching.

## When you are done

Say plainly:

- #01's cell states before and after, on a real case, and any document where a name was confirmed
  that should not have been
- for #05/#07: `no` before, `no` after, and how many became `rv` — and confirm none became `ok`
- whether you reused `semantic_read.locate_quote` or wrote a second matcher, and why
- whether `ocr_packet` really does run before `match_roster`, as Task 2 assumes
- that these need a re-ingest before they show on an existing case
