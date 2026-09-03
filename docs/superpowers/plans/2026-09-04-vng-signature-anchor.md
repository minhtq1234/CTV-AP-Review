# VNG Signature Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #22 stops being a criterion that ships and finds nothing. Either it locates the VNG
signature block on a contract, or it says out loud that it cannot and why.

**Architecture:** One phrase table, driven by what real contracts say rather than by what a plan
guessed. The mechanism is already merged and works — this is a data problem wearing a code problem's
clothes.

**Tech Stack:** Python 3.11+ · pytest. No frontend change.

---

## What was measured, and by whom

`signature_anchors.find_anchors` shipped in `388284c` and works. Measured over a fresh 25-packet
ingest of the combined-template submission on 2026-09-04:

| criterion | asks for | located |
|---|---|---|
| #21 Hợp đồng có chữ ký CTV | `ctv` on the contract | **25 / 25** |
| #23 BBNT có chữ ký CTV | `ctv` on the BBNT | **24 / 25** |
| #24 BBNT có chữ ký và dấu VNG | `vng` on the BBNT | 12 / 25 |
| **#22 Hợp đồng có chữ ký và dấu VNG** | **`vng` on the contract** | **0 / 25** |
| #25 Phụ lục | `ctv` on the appendix | n/a — this submission has none |
| #28 Bảng Kê Thu Mua | `author` | 0 / 25 — roster-level, no per-packet page |

The branch author independently measured 1 of 25 on their own submission. Two submissions, two
measurements, effectively zero.

**The mechanism is not at fault.** On all 25 contracts the `ctv` anchor is found, on page 3 every
time. The same function, on the same page, finds nothing for `vng`. So the phrases are wrong, not the
locator:

```python
_PHRASES = {
    norm("Bên Cung Ứng Dịch Vụ"): "ctv",     # found, 25/25
    norm("Đại diện Bên B"):       "ctv",
    norm("Bên Sử Dụng Dịch Vụ"):  "vng",     # found 0/25 on a contract
    norm("Đại diện Bên A"):       "vng",
    norm("Đại diện VNG"):         "vng",
}
```

That `vng` works on 12 of 25 **BBNTs** and 0 of 25 **contracts** is the clue: the two document types
word their signing headers differently, and the table was built from the BBNT's vocabulary.

---

## Do not add phrases by guessing

The previous round of this cost real time: a plan guessed five phrases, three landed, two never
matched anything. **Read the contracts first.** Task 1 exists only to produce that list, and it must
be finished before Task 2 changes a line of `_PHRASES`.

---

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

- **`pytest` must run with `server/` as the working directory.**
- Baseline at the time of writing: **929 server, 402 UI, `tsc -b` clean** — on the branch alone.
  Establish your own and compare.
- **Do not touch `server/app.py` or `server/app_test.py`.** Another session has ~208 lines of
  uncommitted work there, and two of its tests already fail against merged `main` because
  `eb05f7d` legitimately changed a `findingCount` from 15 to 14. Not yours to reconcile.
- **A case ingested before your change keeps its old anchors.** Re-ingest to see anything.

**There is a good case to work against:** `ba5ab48df63448fb81916694cc25b992`, a 25-packet ingest of
the combined template from 2026-09-04, with 25/25 roster matches and contract `ctv` anchors on every
packet. It is the case every number above came from.

---

## Task 1: Read what the contracts actually say

**Files:**
- Create: `server/tools/read_signing_headers.py` (a throwaway probe, committed so the next person
  need not rebuild it)

- [ ] **Step 1: Print the text around the known-good anchor**

The `ctv` anchor is found on page 3 of all 25 contracts. A Vietnamese contract signs both parties
side by side, so the VNG header is almost certainly **on the same lines, to the right**. Write a
probe that, for each of the 25 packets:

1. reads `packets/<n>/manifest.json` and finds the contract's `anchors.ctv.page`
2. re-reads that page's words — you will need `ocr_extract`'s page reader, since the manifest keeps
   no words (this is why the anchors are recorded at ingest in the first place)
3. prints every line on that page whose y is within ±3 line-heights of the `ctv` anchor, with each
   word's x, so the right-hand column is visible

- [ ] **Step 2: Report the phrases, with counts**

Output a frequency table of the candidate headers, not a prose summary:

```
   25  BÊN CUNG ỨNG DỊCH VỤ        (the ctv anchor, for control)
   nn  <whatever sits to its right>
   nn  <second most common>
```

**Report this table before writing any code in Task 2.** If the right-hand column turns out to be
blank on most contracts — i.e. VNG genuinely does not sign in a labelled block on this template —
then **#22 cannot be located and that is the finding**. Go to Task 3 instead.

- [ ] **Step 3: Commit the probe**

```bash
git add server/tools/read_signing_headers.py
git commit -m "tools: print the signing headers a contract actually uses"
```

---

## Task 2: Add only the phrases you saw

**Files:**
- Modify: `server/signature_anchors.py`
- Modify: `server/signature_anchors_test.py`

- [ ] **Step 1: Write one failing test per phrase Task 1 found**

One test each, quoting the real header verbatim in the fixture. Follow the existing tests in that
file — they already build word dicts by hand.

Mind the trap the module's own comment records: bare `Bên A` occurs throughout a BBNT's prose, so an
unqualified phrase matches body text and, being assigned last, overwrites the real header. Prefer
the qualified form, and if you must use a short phrase, add a test proving it does not match body
prose.

- [ ] **Step 2: Run red, add the phrases, run green**

Only phrases from Task 1's table. **No speculative additions** — an unmatched phrase costs nothing
at runtime but it makes the table lie about what has been verified, which is how it got into this
state.

- [ ] **Step 3: Re-ingest and measure again**

```bash
cd server && python3 -m uvicorn app:app --host 127.0.0.1 --port 8002
# then POST the same input as case ba5ab48d... and sweep #21-#25, #28 as before
```

**Report the same table as at the top of this plan, with your numbers.** #22 must move off 0/25 or
this task has not landed. Do not report "it should now work".

- [ ] **Step 4: Commit**

```bash
git add server/signature_anchors.py server/signature_anchors_test.py
git commit -m "fix(anchors): the headers a contract really uses for the VNG side"
```

---

## Task 3: If it cannot be located, say so in the cell

Only if Task 1 shows there is no VNG header to find on this template.

A criterion that silently points nowhere is the defect being fixed here. If the block genuinely is
not labelled, the honest outcome is a cell that says so.

- [ ] **Step 1: Give the note the reason**

`_presence` already distinguishes a located block from an unlocated one. Where no anchor exists, the
note should say the block could not be located on this document rather than implying it was found —
the same discipline `pendingReason` applies to `?` cells.

- [ ] **Step 2: Do not change the status**

It stays `rv`. A block that cannot be located is not a failed check; the reviewer still has to look,
just without help. **Do not resolve it to `no`.**

- [ ] **Step 3: Commit**

```bash
git commit -m "fix(criteria): say when a signature block could not be located"
```

---

## When you are done

Say plainly:

- Task 1's frequency table, verbatim
- the located-rate table with your own numbers, all six criteria
- whether #28's `author` anchor is findable at all, or whether a roster-level document has no
  per-packet page to anchor in — that is still unexplained
- whether you took Task 2 or Task 3, and why
- that a case ingested before your change keeps its old anchors
