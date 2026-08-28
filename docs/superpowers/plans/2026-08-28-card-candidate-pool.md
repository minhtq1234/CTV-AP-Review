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
- **Do not touch `server/app.py` or `server/app_test.py`** — another session has uncommitted work
  in them.

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
