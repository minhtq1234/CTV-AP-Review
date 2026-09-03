# Finish the Half-Built Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nine of the twenty-five criteria stop being half-finished — six start pointing at the
right page, two start reading the ID card, and one gets answered either way.

**Architecture:** Everything here is an **ingest-side** change plus a small read of it at check
time. That is forced, not chosen: the saved manifest keeps only `{src, width, height}` per page, so
every word box is discarded once the read finishes. Anything that needs to point at a place on a
page has to record that place while the words are still in hand.

**Tech Stack:** Python 3.11+ · pytest, plus one small TypeScript change for the last task.

---

## What is deferred, and where it went

#6 (Trạng thái MST) and #27 (Thông tin công ty VNG) are **deferred** — both need information from
outside the code rather than code, so neither is in this plan or the semantic one. #27's comparison
machinery does get built as a side effect of `compare="organisation"` in
`2026-08-28-semantic-extraction.md`; it will answer `UNKNOWN` until somebody supplies VNG's and
Adtima's own legal details, which is correct and honest rather than a gap.

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

- **`pytest` must run with `server/` as the working directory** — the modules import each other
  flat (`import roster_checks`), so running from the repo root fails on imports.
- The `npm`/`npx` wrappers may throw `EPERM: uv_cwd`; if so call `node_modules/.bin/...` directly.
- `tsconfig.json` sets `noUnusedLocals` and `noUnusedParameters`, so introduce each import in the
  task that first uses it.

**Green before every commit:** `cd server && python3 -m pytest -q` and, for the last task,
`node_modules/.bin/vitest run` plus `node_modules/.bin/tsc -b`. At the time of writing: **821
server, 367 UI, tsc clean.** Establish your own baseline first.

**`server/app.py` and `server/app_test.py` are free to change.** They were held back while
another session had uncommitted work in them; that work landed in `7624a3e` on 2026-08-28 and
the tree is clean. Do not stop on this.

**Everything in Tasks 1–4 needs a re-ingest to show up.** Results are baked at upload time, so
existing cases keep their old answers until the submission is put through again. Say this in your
report so nobody concludes the work did nothing.

---

## What is actually wrong, in one look

`server/evaluate.py:510`, the whole of what a signature criterion offers the reviewer today:

```python
Evidence(d.get("id", ""), 0, None, "", None, "ocr")
```

Page `0`. Bounding box `None`. Meanwhile the cell's own note tells the reviewer
*"công cụ chỉ dẫn đến vị trí"* — the tool guides you to the position. A contract is four pages and
the signatures are on the last one. The verdict half of these criteria is correct and deliberate
(they must never auto-resolve); the locating half was never built.

For the card: `server/cccd_idp.py:49` `IdpRead` carries `id_number`, `name`, `dob` **and a `fields`
dict of everything the service returned**. The stored card record keeps only the number, so the
name and date of birth are read and thrown away on every card of every submission.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/signature_anchors.py` **(create)** | Pure: find signature/stamp blocks in a page's words. |
| `server/signature_anchors_test.py` **(create)** | Unit tests, no OCR needed. |
| `server/ocr_extract.py` **(modify)** | Record the anchors it finds into the manifest. |
| `server/evaluate.py` **(modify)** | `_presence` points at a recorded anchor. |
| `server/cccd_ingest.py` **(modify)** | Persist the card's name and date of birth. |
| `server/cccd_idp.py` **(modify, Task 4 only)** | Surface gender if the service returns it. |
| `src/components/CaseDetail.tsx` **(modify, Task 5)** | The Tổng hợp decision. |

---

## Task 1: Find a signature block in a page's words

**Files:**
- Create: `server/signature_anchors.py`
- Create: `server/signature_anchors_test.py`

- [ ] **Step 1: Read the word shape first**

`ocr_extract` works in "word dicts". Read `server/idp_words.py`'s `parse_words` docstring and one
of its tests to confirm the exact keys before writing anything. This plan assumes each word is
`{"text": str, "page": int, "x": int, "y": int, "w": int, "h": int, "conf": float}`. **If it
differs, follow the code and say so in your report** — do not adapt the code to this plan.

- [ ] **Step 2: Write the failing test**

```python
# server/signature_anchors_test.py
from signature_anchors import find_anchors


def _w(text, page, x, y, w=80, h=14):
    return {"text": text, "page": page, "x": x, "y": y, "w": w, "h": h, "conf": 0.9}


def test_finds_the_contractor_side_on_the_page_it_appears_on():
    words = [
        _w("ĐIỀU", 0, 40, 100), _w("1", 0, 90, 100),
        _w("BÊN", 3, 40, 900), _w("CUNG", 3, 90, 900), _w("CẤP", 3, 150, 900),
        _w("DỊCH", 3, 200, 900), _w("VỤ", 3, 260, 900),
    ]

    anchors = find_anchors(words)

    assert anchors["ctv"]["page"] == 3
    box = anchors["ctv"]["bbox"]
    # The region covers the phrase and the space beneath it, where a signature
    # actually goes -- pointing at the words alone would highlight the label.
    assert box["y"] <= 900
    assert box["y"] + box["h"] > 900 + 14


def test_finds_the_company_side_separately():
    words = [
        _w("ĐẠI", 1, 400, 800), _w("DIỆN", 1, 450, 800), _w("VNG", 1, 520, 800),
    ]
    anchors = find_anchors(words)
    assert anchors["vng"]["page"] == 1
    assert "ctv" not in anchors


def test_returns_nothing_rather_than_guessing():
    """No anchor found must stay empty. A wrong highlight is worse than none:
    it tells the reviewer the tool knows where to look when it does not."""
    assert find_anchors([_w("Hello", 0, 10, 10)]) == {}


def test_matches_regardless_of_case_and_accents():
    """OCR drops and mangles diacritics constantly -- see the packet whose CCCD
    read cleanly while its label did not."""
    words = [_w("BEN", 2, 40, 500), _w("CUNG", 2, 90, 500), _w("CAP", 2, 150, 500),
             _w("DICH", 2, 200, 500), _w("VU", 2, 260, 500)]
    assert find_anchors(words)["ctv"]["page"] == 2


def test_the_last_occurrence_wins():
    """A contract names both parties in its opening paragraph and again at the
    signature block. The block is the later one."""
    words = [_w("BÊN", 0, 40, 200), _w("CUNG", 0, 90, 200), _w("CẤP", 0, 150, 200),
             _w("DỊCH", 0, 200, 200), _w("VỤ", 0, 260, 200),
             _w("BÊN", 3, 40, 900), _w("CUNG", 3, 90, 900), _w("CẤP", 3, 150, 900),
             _w("DỊCH", 3, 200, 900), _w("VỤ", 3, 260, 900)]
    assert find_anchors(words)["ctv"]["page"] == 3
```

- [ ] **Step 3: Run it red**

```bash
cd server && python3 -m pytest signature_anchors_test.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'signature_anchors'`.

- [ ] **Step 4: Implement**

```python
# server/signature_anchors.py
"""Where the signature and stamp blocks sit on a document's pages.

Six criteria (#21-#25, #28) are locate-and-look: the tool points, the person
decides. The pointing half never existed -- `_presence` handed the viewer page 0
with no box -- because the manifest keeps no word boxes, so there is nothing to
search at check time. This runs during the read, while every word is still in
hand, and records what it finds.

Two anchors, because the criteria distinguish them: the contractor's side and
VNG's side.
"""
from __future__ import annotations

import re
import unicodedata

#: Phrase -> anchor name. Folded (lowercase, accent-stripped) before matching,
#: because OCR loses diacritics routinely.
_PHRASES = {
    "ben cung cap dich vu": "ctv",
    "ben b": "ctv",
    "dai dien vng": "vng",
    "dai dien ben a": "vng",
    "nguoi lap bieu": "author",
}

#: How far below the phrase the signature itself sits, as a multiple of the
#: phrase's own line height. A signature block is roughly four lines tall.
_BLOCK_LINES = 4


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text or "")
    stripped = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", stripped.replace("đ", "d").replace("Đ", "D")).strip().lower()


def find_anchors(words: list[dict]) -> dict[str, dict]:
    """`{anchor_name: {"page": int, "bbox": {"x","y","w","h"}}}`.

    Empty when nothing matched. A phrase found more than once resolves to its
    LAST occurrence: a contract names both parties in its opening paragraph and
    again where they sign, and it is the signature block we want.
    """
    by_page: dict[int, list[dict]] = {}
    for word in words:
        by_page.setdefault(int(word.get("page", 0)), []).append(word)

    found: dict[str, dict] = {}
    for page in sorted(by_page):
        line_words = sorted(by_page[page], key=lambda w: (w.get("y", 0), w.get("x", 0)))
        joined = _fold(" ".join(str(w.get("text", "")) for w in line_words))
        for phrase, name in _PHRASES.items():
            if phrase not in joined:
                continue
            hit = _locate(line_words, phrase)
            if hit is not None:
                found[name] = {"page": page, "bbox": hit}
    return found


def _locate(line_words: list[dict], phrase: str) -> dict | None:
    """The box covering `phrase` plus the signing space beneath it."""
    target = phrase.split()
    for start in range(len(line_words)):
        window = line_words[start:start + len(target)]
        if len(window) < len(target):
            break
        if _fold(" ".join(str(w.get("text", "")) for w in window)) != phrase:
            continue
        x = min(int(w.get("x", 0)) for w in window)
        y = min(int(w.get("y", 0)) for w in window)
        right = max(int(w.get("x", 0)) + int(w.get("w", 0)) for w in window)
        height = max(int(w.get("h", 0)) for w in window) or 14
        return {"x": x, "y": y, "w": right - x, "h": height * (_BLOCK_LINES + 1)}
    return None
```

- [ ] **Step 5: Run green and commit**

```bash
cd server && python3 -m pytest signature_anchors_test.py -q
```
Expected: 5 passed.

```bash
git add server/signature_anchors.py server/signature_anchors_test.py
git commit -m "feat(ocr): locate the signature and stamp blocks in a page's words"
```

---

## Task 2: Record the anchors during the read

**Files:**
- Modify: `server/ocr_extract.py`
- Modify: `server/ocr_extract_test.py`

- [ ] **Step 1: Find where a document's words are still available**

`ocr_packet` (around line 1730) returns
`{"folder": {"docs": [...], "fields": [...]}, "identity": {...}}`. Find the point where it has both
a document's identity and the words for that document's pages. **Read it before editing** and note
the variable names in your report.

- [ ] **Step 2: Write the failing test**

Add to `server/ocr_extract_test.py`, following that file's existing fixture style:

```python
def test_a_document_records_where_its_signature_blocks_are():
    """The six locate-and-look criteria read this. Without it they can only
    offer page 0 with no box, while their own note promises otherwise."""
    # build a packet whose contract page 3 carries "BÊN CUNG CẤP DỊCH VỤ",
    # run ocr_packet over it with a stubbed page reader, then:
    contract = next(d for d in result["folder"]["docs"] if d["kind"] == "contract")
    assert contract["anchors"]["ctv"]["page"] == 3
    assert contract["anchors"]["ctv"]["bbox"]["h"] > 0
```

Fill it in against the real fixtures in that file — it already stubs a page reader somewhere, so
follow that rather than inventing one.

- [ ] **Step 3: Run red, implement, run green**

Each doc dict gains `"anchors": find_anchors(words_for_that_doc)` — `{}` when nothing is found, so
the key is always present and the reader never has to test for it.

**Do not store the words themselves.** A 314-page submission would bloat every manifest for no
gain; the anchors are two small boxes.

- [ ] **Step 4: Commit**

```bash
git add server/ocr_extract.py server/ocr_extract_test.py
git commit -m "feat(ocr): save each document's signature-block positions"
```

---

## Task 3: Point the six criteria at them

**Files:**
- Modify: `server/evaluate.py`
- Modify: `server/evaluate_test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_signature_criterion_points_at_the_block_it_found():
    """#21 must send the reviewer to the page the signature is on, with a box.
    It used to offer page 0 and no box on a four-page contract."""
    # a packet whose contract carries anchors {"ctv": {"page": 3, "bbox": {...}}}
    result = evaluate_criterion(21, packet, roster)
    cell = result.cells[0]
    assert cell.status is Status.REVIEW          # unchanged: still a person's call
    assert cell.evidence[0].page == 3
    assert cell.evidence[0].bbox is not None


def test_a_signature_criterion_with_no_anchor_still_asks_for_a_person():
    """No anchor found must not become a wrong highlight, and must not become a
    different verdict either -- it stays `rv`, just without a location."""
    result = evaluate_criterion(21, packet_without_anchors, roster)
    cell = result.cells[0]
    assert cell.status is Status.REVIEW
    assert cell.evidence[0].bbox is None
```

Match `evaluate_test.py`'s real helper names — it has its own way of building a packet and calling
one criterion. Follow it.

- [ ] **Step 2: Run red, then implement**

In `_presence`, replace the fixed `Evidence(d.get("id", ""), 0, None, "", None, "ocr")` with one
built from the document's recorded anchors. Which anchor depends on the criterion:

| criterion | anchor |
|---|---|
| #21 Hợp đồng có chữ ký CTV | `ctv` |
| #22 Hợp đồng có chữ ký và dấu/giáp lai VNG | `vng` |
| #23 BBNT có chữ ký CTV | `ctv` |
| #24 BBNT có chữ ký và dấu/giáp lai VNG | `vng` |
| #25 Phụ lục/KPI có ký, dấu đầy đủ | `ctv`, falling back to `vng` |
| #28 Bảng Kê Thu Mua có chữ ký người lập | `author` |

Put that mapping in `server/criteria.py` as a param on those criteria (`anchor="ctv"`), not as a
dict of magic STT numbers in `evaluate.py` — the criteria file is where a criterion's facts live.

**The statuses must not change.** These stay `rv` (or `missing`, or `na` for #25's "nếu có").
If any existing test's status changes, you have broken the design rule — stop and report.

- [ ] **Step 3: Run the whole suite, then commit**

```bash
cd server && python3 -m pytest -q
git add server/evaluate.py server/evaluate_test.py server/criteria.py
git commit -m "feat(criteria): send the signature checks to the right page"
```

---

## Task 4: Keep the card's name, date of birth, and gender if it is there

**Files:**
- Modify: `server/cccd_ingest.py`
- Modify: `server/cccd_ingest_test.py`

This is the cheapest win in the whole backlog. `IdpRead` (`server/cccd_idp.py:49`) already carries
`name` and `dob`, plus a `fields` dict of **everything** the service returned. The stored card keeps
only `number`, so the rest is discarded on every card of every submission — which is the only
reason #1 and #3 show `?` in the CCCD/Passport column.

- [ ] **Step 1: Write the failing test**

```python
def test_a_stored_card_keeps_the_name_and_date_of_birth_it_read():
    """Both were already read and then thrown away, which is the only reason
    criteria #1 and #3 show `?` in the CCCD/Passport column."""
    # ingest one card whose reader returns name and dob, then:
    card = cards[0]
    assert card["name"] == "NGUYEN VAN MOT"
    assert card["dob"] == "01/01/1990"


def test_a_stored_card_keeps_gender_when_the_reader_returns_it():
    """#4's CCCD column depends entirely on whether it comes back. If the
    reader gives nothing, the key must be absent rather than an empty string --
    absent means "not read", empty would read as "read as blank"."""
    # with a reader whose `fields` carries a gender entry:
    assert cards[0]["gender"] == "Nam"
    # and with one that does not:
    assert "gender" not in other_cards[0]
```

- [ ] **Step 2: Run red, then implement**

Persist `name` and `dob` on the card record. For gender, look through `IdpRead.fields` for a key
matching `sex|gender|gioi tinh` (folded), and set it **only when found**.

Then feed these into the packet's field sources so the criteria engine sees them, the same way the
card's `cccd` already reaches `fields`. Find how `cccd` gets there and follow it exactly — do not
invent a second route.

- [ ] **Step 3: Report the #4 answer**

Whether the reader returns gender is the open question this task settles. **State the answer
plainly in your report**, because it decides whether #4 is finished or blocked. You may need the
service's access keys to find out; if you do not have them, say that rather than guessing.

- [ ] **Step 4: Commit**

```bash
git add server/cccd_ingest.py server/cccd_ingest_test.py
git commit -m "feat(cccd): keep the name, date of birth and gender read from a card"
```

---

## Task 5: Decide Tổng hợp

**Files:**
- Modify: `src/components/CaseDetail.tsx`
- Modify: `src/components/caseDetail.test.tsx`

The tab was hidden because backing out of a packet landed there instead of on the packet list. That
bug is fixed at its root — `UploadFlow` no longer holds a write-once `detailTab` — so the flag is
now the only thing keeping it off, and five criteria (#20, #26, #30, #31, #32) have nowhere to
appear.

- [ ] **Step 1: Check the bug really is gone before restoring anything**

Set `SHOW_SUMMARY_TAB = true` in `src/components/CaseDetail.tsx`, run the app, and try the exact
sequence that produced it: open a packet → click a `Bảng Kê Thu Mua` cell in 25 tiêu chí → land on
Tổng hợp → go to Gói hồ sơ → open a packet → press back. **You must end on the packet list.**

If you end on Tổng hợp, stop. Restore the flag to `false`, report it, and do not continue — the
root fix is incomplete and guessing at it here will hide it again.

- [ ] **Step 2: If it behaves, restore the tab**

Flip the flag, and flip `caseDetail.test.tsx`'s two tests back to asserting both tabs are offered —
the comment above them says exactly this would happen. Also restore the matrix's jump: pass
`onShowSummary` again from `UploadFlow`, **clearing the pending tab once it has been used** so it
cannot become sticky a second time.

- [ ] **Step 3: Verify and commit**

```bash
node_modules/.bin/vitest run && node_modules/.bin/tsc -b
git add src/components/CaseDetail.tsx src/components/caseDetail.test.tsx src/components/UploadFlow.tsx
git commit -m "feat(cases): bring back Tổng hợp, without the sticky tab"
```

---

## When you are done

Say plainly:

- whether the word dicts matched what Task 1 assumed, and what they really are
- **does the card reader return gender** — this is the answer to #4
- whether the Tổng hợp back-button sequence behaved, in the exact words of what you saw
- your real test numbers against your baseline
- that these changes need a re-ingest before they show on an existing case

---

## Outcome — partial, 2026-08-29

**Tasks 1–3 and Task 5 done. Task 4 (dob/gender off the card) not started.**

**The word dicts did not match what Task 1 assumed, and this is the important one.** A word is
`{text, x, y, w, h, conf}` — six keys, **no `page`** — produced by `ocr_extract.ocr_words` and
`idp_words.parse_words`, and `scale_words` rebuilds it from exactly those six, so an extra key would
be dropped in transit anyway. Page is *structural*: `words_by_doc: {docId: {page: [word]}}`. The
plan's `int(word.get("page", 0))` would therefore have been a constant `0` on real data —
reproducing the exact defect the task exists to remove, with the plan's own tests green, because its
`_w(text, page, …)` fixture invents the key the pipeline never produces. The locator takes a
document's `{page: [word]}` map instead.

Three smaller corrections, same cause — the plan describing a shape the code does not have:

- Bboxes here are `{x, y, width, height}`; the plan's `_locate` returned `{x, y, w, h}`, which is
  truthy and renders as a zero-size highlight — a value that looks located and is not.
- The corpus says **`Bên Cung Ứng Dịch Vụ`**, not *Cung Cấp*. Bare `Bên B` is prose throughout a real
  BBNT and, assigned unconditionally, would overwrite the real header; `Đại diện Bên B` is used.
- **Five criteria, not six.** #28 is unreachable: its documents are `[PURCHASE]`, which `_presence`
  short-circuits fifteen lines above the evidence site and which `DOC_KINDS` has no entry for. That
  is deliberate — the bảng kê is batch-level and is answered as #26 on Tổng hợp — so no `anchor` was
  added to it and the short-circuit was left alone.

**Does the card reader return gender — unanswered.** Task 4 was not started, so #4 is still open.

**The Tổng hợp back-button sequence, in the exact words of what I saw.** Opened packet 1 → clicked
the cell labelled `Họ và tên · Bảng Kê Thu Mua: Chưa kiểm tra được` → landed on **`Tổng hợp*`** →
switched to Gói hồ sơ → opened packet 2 → pressed `←` → ended on **`Gói hồ sơ*` with 25 packet rows.**
The bug is gone.

**A second stickiness path the plan does not mention.** Clearing the pending tab only on packet-open
leaves it at `summary`, so leaving to the case list after a jump and re-entering the case *also*
landed on Tổng hợp. Milder than the original, same class. It is now cleared on opening a case as
well, making the jump strictly one-shot; verified by re-entry landing on `Gói hồ sơ*`.

**Test numbers.** Baseline 836; **851 passing** after Tasks 1–3 and 5. The plan's stated 821 was
never reproducible here.

**These changes need a re-ingest before they show on an existing case.** Anchors are recorded during
the read, so every case ingested before this keeps page 0 and no box until it is put through again.

### Measured on a whole real case, and verified on screen

Superseding the four-contract sample this section first carried. A 25-packet submission was
re-ingested on this code and every manifest counted:

| document | n | ctv | vng |
|---|---|---|---|
| contract | 25 | **25 (100%)** | **1 (4%)** |
| bbnt | 24 | **21 (88%)** | **10 (42%)** |

57 boxes recorded, heights 216–288px.

**#21 and #23 are delivered. #22 is not, and should not be described as such** — one contract in
twenty-five. `Đại diện VNG` is mangled by OCR essentially always, so #22 gets the right document and
the right signing page and never a box. #24 lands at 42%, better because a BBNT prints
`Bên Sử Dụng Dịch Vụ` as a column header rather than a signature caption.

**#25 is unverified.** This submission contains no appendix documents at all, so nothing exercised
it. Anyone claiming it works needs a case that has one.

**Verified in the running app**, not only in tests. Clicking #21's cell opened the popup on page 4 of
the contract with the box over the right-hand signature column, enclosing the
`BÊN CUNG ỨNG DỊCH VỤ` header, the signature and the printed name — the VNG seal in the left column
correctly outside it. The rendered CSS is exactly `inflateBbox({x:721, y:874, w:221, h:234}, 0.2)`
against a 1241×1755 page, matching the recorded anchor to the decimal. Re-opened fresh, the viewer's
`scrollTop` is 0: the box is drawn and the page does not jump, so ver-3 scope §2's "no autofocus"
holds. #22's cell opened the same document with no box, as predicted.

This also settles `_BLOCK_LINES`: at 9 the box reaches the printed name under the signature, which is
what the reviewer is actually checking. The value this plan proposed would have cropped it.

**The `anchors` key is not universal.** It is set on every document `assemble_docs` builds, but
`cccd_ingest` attaches the card documents afterwards and those carry none — 14 of them on this case.
Harmless (`_block_evidence` reads it with `.get("anchors") or {}`, and no signature criterion looks
at a card), but not a whole-manifest guarantee.

**Nothing showed a reviewer these boxes when Tasks 1–3 landed.** `EvidenceViewer`'s `focusBbox` is
fed by the field-selection path, and the packet-docs popup runs `overviewMode` permanently, which
made `focusBbox` inert there. `overviewMode` conflated the jump to a value with the outline around
it; `showFocusInOverview` now draws without scrolling, which is what let the above be verified at all.
