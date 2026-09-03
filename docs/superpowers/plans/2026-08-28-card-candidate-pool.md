# Card Candidate Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The CCCD review step shows the reviewer the cards that actually need assigning — about
five on the combined workbook — instead of 81.

**Architecture:** One change, at the point where candidates are formed. A bank or tax screenshot
must never become a card candidate at all, rather than being formed and then discounted.

**Tech Stack:** Python 3.11+ · pytest. No frontend change.

---

## Credit

Found in review by the author of `docs/superpowers/plans/2026-08-28-semantic-extraction.md`'s
question 5, while verifying that plan against a real ingest of the combined workbook. The diagnosis
below is theirs; it was reproduced independently before this plan was written.

---

## The defect

On the combined workbook, `cccdSummary` reports `candidates: 100, attached: 19, unresolved: 81`.
The reviewer is handed 81 unmatched "cards" to assign by hand. The real number is nearer five.

The workbook holds 100 drawings, of which only 48 are card sides:

| where | kind | count |
|---|---|---|
| `CCCD!D` | card | 24 |
| `CCCD!E` | card | 24 |
| `CCCD!G` | bank | 25 |
| `MST!D` | tax | 18 |
| `MST!C`, `CCCD!C` | *(unclassified)* | 9 |

`_pairable` (`server/cccd_pairing.py:74`) does exactly the right thing — a drawing whose column
header says bank or tax is never one half of a card — **but it is referenced in only one place**,
line 92, inside `_vertically_eligible`. So it prevents a screenshot being *paired with* a card, and
nothing more.

`_component_candidates` (`:104`) then does this to every component it is given:

```python
if len(component) != 2:
    issue = "ambiguous-pair" if len(component) > 2 else None
    return [_single_candidate(image, issue) for image in component]
```

So each bank screenshot, each tax screenshot and each unclassified image becomes its own
`CardCandidate` carrying `unknown-side` or `missing-back`. `cccd_ingest.py:703` then counts the pool
with `len(mappings)`, and every one of those shows up as an unresolved CCCD.

**This makes the ver-3 CCCD review step unusable on the combined template**, which is the template
the tool is being pointed at now. It is not a cosmetic count.

## Fix it at formation, not at the count

Subtracting non-cards at the count would leave the same wrong candidates flowing into
`resolve_candidates` and `plan_candidate_mappings`, where they can still consume a roster row or
raise a duplicate-id error. Drop them before components are formed.

**The rule already exists** — `_pairable` is precisely it. Apply it at the entry to
`pair_drawings`, not only deep inside eligibility.

**Do not filter on "has a kind".** `kind is None` means the sheet declared no image headers at all
— the July `cccd.xlsx` — and that path must keep today's proximity pairing exactly. Only a drawing
whose kind is a *known non-card* kind gets dropped. `_pairable` already expresses that distinction;
read its docstring before touching it.

---

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

- **`pytest` must run with `server/` as the working directory.**
- Establish your own test baseline before changing anything and compare against it.
- **`server/app.py` and `server/app_test.py` are free to change.** They were held back while
  another session had uncommitted work in them; that work landed in `7624a3e` on 2026-08-28 and
  the tree is clean. Do not stop on this.

**This fix changes ingest output, so an existing case keeps its wrong count until it is put through
again.** Say so in your report.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/cccd_pairing.py` **(modify)** | Keep non-card drawings out of the candidate pool. |
| `server/cccd_pairing_test.py` **(modify)** | Prove they stay out, and that the no-header path is untouched. |
| `server/cccd_ingest_test.py` **(modify)** | Prove the summary the reviewer sees is card-only. |

---

## Task 1: Non-card drawings never become candidates

**Files:**
- Modify: `server/cccd_pairing.py`
- Modify: `server/cccd_pairing_test.py`

- [ ] **Step 1: Reproduce the count in a test first**

Before changing any behaviour, write a test that fails with today's code and states the real numbers.
`server/cccd_pairing_test.py` already has builders for analyzed drawings with a `kind` — reuse them,
do not invent new ones.

```python
def test_screenshots_do_not_enter_the_candidate_pool():
    """A bank or tax screenshot is not half a card and not a whole one either.
    They used to become single candidates with `unknown-side`, so the combined
    workbook offered the reviewer 81 unresolved cards where about five need
    attention -- which made the CCCD review step unusable on that template."""
    images = [
        _analyzed("front-1", kind="card", col=3, row=1),
        _analyzed("back-1",  kind="card", col=4, row=1),
        _analyzed("bank-1",  kind="bank", col=6, row=1),
        _analyzed("tax-1",   kind="tax",  col=3, row=1),
    ]

    candidates = pair_drawings(images)

    assert len(candidates) == 1
    ids = {d.drawing.id for c in candidates for d in (c.front, c.back) if d}
    assert ids == {"front-1", "back-1"}


def test_an_unclassified_drawing_still_becomes_a_candidate():
    """`kind is None` means the sheet declared no image headers -- the July
    cccd.xlsx. That path keeps proximity pairing exactly as it was, so an
    unclassified drawing must still be offered to the reviewer."""
    images = [_analyzed("lone", kind=None, col=3, row=1)]
    assert len(pair_drawings(images)) == 1
```

- [ ] **Step 2: Run it red**

```bash
cd server && python3 -m pytest cccd_pairing_test.py -q -k "candidate_pool or unclassified"
```
Expected: the first test FAILS reporting 4 candidates rather than 1. The second should already pass —
if it does not, stop: the no-header path is different from what this plan assumes.

- [ ] **Step 3: Implement**

In `pair_drawings` (`:24`), filter before components are formed:

```python
def pair_drawings(images: list[AnalyzedDrawing]) -> list[CardCandidate]:
    if len({image.drawing.id for image in images}) != len(images):
        raise ValueError("duplicate drawing id")
    # A drawing the header identifies as a bank or tax screenshot is not a card
    # side and is not a lone card either, so it must not reach
    # `_component_candidates` -- that function turns every image in a component
    # into its own candidate, which is how 52 screenshots became 52 unresolved
    # CCCDs on the combined workbook. `_pairable` was already the right rule; it
    # was only ever consulted when deciding whether two drawings pair.
    images = [image for image in images if _pairable(image)]
    candidates = [...]
```

Leave the check at line 92 alone. It is now redundant for the filtered path but still correct, and
`_vertically_eligible` is called from more than one place — verify that before considering its
removal, and if you do remove it, say why in your report.

- [ ] **Step 4: Run the whole pairing suite**

```bash
cd server && python3 -m pytest cccd_pairing_test.py -q
```
Expected: your baseline plus the new test. **The existing `test_aggregate_layout_groups_yield_29_pairs_and_3_singles`
must still pass unchanged** — it is the regression guard for real layouts. If its numbers move, the
filter is dropping something it should not; stop and report rather than editing that test's numbers.

- [ ] **Step 5: Commit**

```bash
git add server/cccd_pairing.py server/cccd_pairing_test.py
git commit -m "fix(cccd): keep bank and tax screenshots out of the card candidate pool"
```

---

## Task 2: The count the reviewer sees

**Files:**
- Modify: `server/cccd_ingest_test.py`

- [ ] **Step 1: Assert the summary, not just the pairing**

The count lives at `server/cccd_ingest.py:703` (`"candidates": len(mappings)`), and after Task 1 it
should already be right. Prove it at that level too, because the summary is what reaches the screen
and it is the number that was wrong:

```python
def test_the_summary_counts_cards_and_not_screenshots():
    """cccd_ingest.py:703 counts the candidate pool. With screenshots filtered
    at formation this needs no arithmetic of its own -- this test is here so that
    if anyone reintroduces them, the failure names the screen it breaks."""
    # ingest a workbook with 2 card sides, 1 bank and 1 tax screenshot
    assert result["cccdWorkbook"]["summary"]["candidates"] == 1
    assert result["cccdWorkbook"]["summary"]["unresolved"] <= 1
```

Follow that file's existing fixture style. **Do not add arithmetic to `cccd_ingest.py`** — if this
test needs a code change there, Task 1 is incomplete and that is the finding.

- [ ] **Step 2: Run the full suite and commit**

```bash
cd server && python3 -m pytest -q
git add server/cccd_ingest_test.py
git commit -m "test(cccd): the reviewer's unresolved count is card-only"
```

---

## Task 3: Say what was skipped

Silently dropping 52 images is the same class of mistake as silently counting them — the reviewer
cannot tell a workbook with no cards from one whose cards were all classified as something else.

- [ ] **Step 1: Decide where it belongs, and say so before building it**

Two candidates. `POST /api/uploads/inspect` already declares image columns and their kinds before a
run starts, and may already answer this — **check it first, and if it does, this task is a no-op and
that is the right outcome.** Otherwise the ingest summary is the place.

- [ ] **Step 2: If it is needed, add a count and test it**

A count per skipped kind, not a list of ids: `{"skippedImages": {"bank": 25, "tax": 18}}`. Enough to
notice, small enough that nobody is tempted to render it as a gallery.

- [ ] **Step 3: Commit only if you built something**

```bash
git commit -m "feat(cccd): report how many non-card images were skipped"
```

---

## When you are done

Say plainly:

- the candidate and unresolved counts before and after, on the combined workbook
- whether `test_aggregate_layout_groups_yield_29_pairs_and_3_singles` still passes untouched
- whether you removed the `_pairable` check at line 92, and why
- whether `/api/uploads/inspect` already answered Task 3
- that an existing case keeps its wrong count until it is re-ingested

---

## Outcome — completed 2026-08-29

**Tasks 1 and 2 implemented; Task 3 was correctly a no-op.**

| | before | after |
|---|---|---|
| candidates | 100 | 25 |
| pairs formed | 0 | 25 of 25 |
| attached automatically | 19, **all false** | 7, all genuine card pairs |
| queued for manual assignment | — | 18 |

**The defect was worse than this plan describes.** It was not only a wrong count: all 19 of the
"attached" cards were tax-lookup screenshots from `MST!D` attached as ID card *fronts*. A tax page
carries a 12-digit number, `_reads_as_front` inferred "front" from it, and resolution matched it to
a packet by that number. No card side had ever been attached on this template, so the yield was
zero rather than low.

**Task 3 needed nothing.** `POST /api/uploads/inspect` (`server/app.py`) already calls
`describe_image_columns`, which reports every image column with its kind and count — including
unclassified ones — *before* a run starts. Checked against the real workbook rather than reasoned
about.

### Two fixes this plan did not contain, without which the above is not reachable

Both were found afterwards, by measuring the real workbook rather than reading it.

**Pairing measured row indices, so nothing could pair.** Every card on this template sits inside one
row, so `to_row == from_row`, so `_vertical_overlap_ratio` sized it at zero and returned `0.0` — for
39 of 50 drawings. `abs(from_row diff) <= 1` was then both the only rule linking a front to its back
*and* the thing chaining all 48 sides into one component of 50, which `_component_candidates` will
never pair. `Anchor` now carries absolute top/bottom in EMU from the sheet's real row heights, and a
`oneCellAnchor` takes its height from `ext/@cy` — that is 100% of the July workbook, whose 42 pairs
were surviving only because equal fabrications score 1.0.

**Classification read the wrong column, off the wrong row, with the wrong matcher.** A drawing is
anchored where its top-left corner falls, which drifts a column left of its header — 9 of 100 real
drawings. The header row was whichever came first with any content, which on both real templates is
a title merged across the whole table. And markers matched as bare substrings, so `anh` matched
`thanh` and a `Thành tiền` column read as a tax screenshot.

### What is still not fixed

The 18 remaining are **awaiting a human, not broken**: `state=manual`, with
`no-number-region` 10, `unreadable-identity` 5, `low-cccd-confidence` 3. Pairing, classification and
roster matching are correct end to end; what caps the *automatic* rate is reading the card image.

**Measured like-for-like against the July submission, which is the only baseline anyone quotes:**

| | July | combined |
|---|---|---|
| matched automatically (`matchMethod=cccd`) | **25 / 42 (60%)** | **7 / 25 (28%)** |
| assigned by hand in the UI (`manual`) | 16 | 0 |
| total attached | 41 | 7 |
| still queued for a human | 1 | **18** |

**Do not compare July's 41 with the combined workbook's 7.** July's 41 includes 16 cards a person
assigned by hand; its automatic rate was 25 of 42, which is what the repo's "24 of 42 on local OCR"
figure refers to. The combined workbook has had no manual work at all.

The gap sits upstream of matching, and in both claim paths: the combined workbook yields a readable
**number** on 10 of 25 cards (40%) against 29 of 42 (69%), and a readable **name** on **1 of 25**
against 7 of 42. The name matters because it is the *fallback* claim —
`cccd_matching._candidate_claims` accepts a roster row by CCCD **or** by a name above a confidence
threshold. On July that fallback rescues cards whose number will not read; here it rescues almost
nothing, which is why the automatic rate is less than half July's.

So the reviewer's real burden on this template is **18 manual assignments out of 25**, not 18 broken
cards. The UI path for that exists and works — it is how July got its 16.

**IDP is aimed at the right step** (reading number and name off the card) but is **unmeasured here**:
no `GREENNODE_*` credential has ever been set on this machine, so every figure above is local
Tesseract. The documented 39-of-42-with-IDP is a July number; do not assume it transfers, because
this workbook is measurably harder for both number *and* name.

Also unverified: that a formed pair is the *same person's* front and back. The 25 pairs are confirmed
to form and 7 to attach automatically; with 18 unread, sameness cannot be established from OCR alone.
