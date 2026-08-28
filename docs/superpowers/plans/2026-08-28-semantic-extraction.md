# Semantic Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The six criteria that need a sentence read rather than a pattern matched — #8, #9, #10,
#11, #13, and #12 free behind them — get a value, an answer, and a place on the page a reviewer can
check.

**Architecture:** A reading step that runs at ingest beside the existing OCR, behind an interface
with a fake implementation. Tasks 1–5 need no model and no network. Task 6 adds the real adapter.
The engine's comparison side is extended first, because `parts` has been declared in the criteria
all along and never read by anything.

**Tech Stack:** Python 3.11+ · pytest. The model is reached over GreenNode's MaaS endpoint, which
this repository already talks to.

---

## Read this before anything else

**Four facts settle decisions you would otherwise have to make.**

**1. The provider is already chosen, and so is the key.** `server/list_models.py` lists models from
`https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`, an OpenAI-compatible endpoint, authenticating
with the **same `GREENNODE_API_KEY`** the ID-card reader already uses. Same vendor, same tenancy,
same approval. Do not introduce a second provider, a second key, or an SDK dependency — a
`urllib` POST to `/chat/completions` is enough, and it is how `idp_words.py` already talks to the
sibling service. Run `python3 list_models.py` to see what the account actually offers; do not
hard-code a model name you have not seen in that output.

**2. Every word box is thrown away after the read.** The saved manifest keeps only
`{src, width, height}` per page. So a model's answer cannot be located on a page at check time —
there is nothing to search. Locating has to happen during the read, while the words are still in
hand, exactly as `signature_anchors` does. This is why Task 4 exists.

**3. The engine cannot compare a multi-part value yet.** `parts=("bank", "branch", "province")` sits
in `server/criteria.py` and **nothing reads it**. `compare="organisation"` has no comparator at
all. Task 1 fixes that, and it is worth doing even if the model half is never built.

**4. A value without a place to check it is worse than no value.** This tool's whole premise is that
it points and a person decides. A model that returns "15 days" with nothing to verify it against
converts a `?` into an unfalsifiable claim. **Every extracted value must carry a verbatim quote and
a page.** If a task cannot produce that, it stops rather than shipping the value.

---

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

- **`pytest` must run with `server/` as the working directory** — the modules import each other
  flat (`import roster_checks`).
- The `npm`/`npx` wrappers may throw `EPERM: uv_cwd`; call `node_modules/.bin/...` directly.

**Green before every commit:** `cd server && python3 -m pytest -q`. At the time of writing, **821
passing**; establish your own baseline.

**Do not touch `server/app.py` or `server/app_test.py`** — another session has ~208 uncommitted
lines in them. If a task needs to, stop and report.

**Never put a real contractor's details in a test.** Use the synthetic series the repo already
uses: `001100000001`, `NGUYEN VAN MOT`, `1900000001`. A real number in a fixture goes to a public
GitHub repository.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/compare_parts.py` **(create)** | Pure: compare a value made of several named parts. |
| `server/compare_parts_test.py` **(create)** | Its tests. |
| `server/evaluate.py` **(modify)** | Use it for `compare="text"`-with-parts and `compare="organisation"`. |
| `server/semantic_read.py` **(create)** | The reader interface, a fake, and quote→box locating. |
| `server/semantic_read_test.py` **(create)** | Everything above, no model needed. |
| `server/semantic_maas.py` **(create, Task 6)** | The real adapter over GreenNode MaaS. |
| `server/ocr_extract.py` **(modify)** | Call the reader during ingest; record values + quotes + boxes. |

---

## Task 1: Compare a value that has several parts

#8 wants bank, branch and province. #13 wants five things out of one clause. #27 wants five company
details. "Three of five present, one of those wrong" is a different answer from "all five present
and one wrong", and the engine has no way to say either today.

**Files:**
- Create: `server/compare_parts.py`
- Create: `server/compare_parts_test.py`

- [ ] **Step 1: Write the failing test**

```python
# server/compare_parts_test.py
from compare_parts import PartsVerdict, compare_parts


def test_all_parts_present_and_agreeing_is_a_match():
    got = {"bank": "Techcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    want = {"bank": "Techcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    result = compare_parts(("bank", "branch", "province"), got, want)
    assert result.verdict is PartsVerdict.MATCH
    assert result.missing == () and result.differing == ()


def test_a_missing_part_is_not_the_same_as_a_wrong_one():
    """The distinction is the point. "The branch is absent" sends the reviewer
    looking for it; "the branch says something else" sends them comparing."""
    got = {"bank": "Techcombank", "province": "TP.HCM"}
    want = {"bank": "Techcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    result = compare_parts(("bank", "branch", "province"), got, want)
    assert result.verdict is PartsVerdict.INCOMPLETE
    assert result.missing == ("branch",)
    assert result.differing == ()


def test_a_differing_part_is_a_mismatch_even_if_the_rest_agree():
    got = {"bank": "Vietcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    want = {"bank": "Techcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    result = compare_parts(("bank", "branch", "province"), got, want)
    assert result.verdict is PartsVerdict.MISMATCH
    assert result.differing == ("bank",)


def test_a_mismatch_outranks_an_absence():
    """Worst-wins, like the rest of the engine's roll-up."""
    got = {"bank": "Vietcombank"}
    want = {"bank": "Techcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    result = compare_parts(("bank", "branch", "province"), got, want)
    assert result.verdict is PartsVerdict.MISMATCH
    assert result.missing == ("branch", "province")
    assert result.differing == ("bank",)


def test_nothing_read_is_unknown_not_a_mismatch():
    """An empty read is the tool admitting it could not see, which is `pending`
    upstream -- never `no`. Getting this backwards would reject valid packets."""
    result = compare_parts(("bank", "branch"), {}, {"bank": "X", "branch": "Y"})
    assert result.verdict is PartsVerdict.UNKNOWN


def test_no_expected_value_is_unknown_too():
    """Nothing to compare against is not agreement."""
    result = compare_parts(("bank",), {"bank": "Techcombank"}, {})
    assert result.verdict is PartsVerdict.UNKNOWN


def test_comparison_tolerates_case_spacing_and_accents():
    """OCR drops diacritics routinely -- see the packet that read a CCCD
    cleanly while mangling its label."""
    got = {"bank": "techcombank", "branch": "TAN  BINH"}
    want = {"bank": "Techcombank", "branch": "Tân Bình"}
    result = compare_parts(("bank", "branch"), got, want)
    assert result.verdict is PartsVerdict.MATCH


def test_the_note_names_what_is_wrong_in_the_reviewers_terms():
    """The note is what the reviewer actually reads, so it has to be specific
    about which part, not just report a count."""
    got = {"bank": "Vietcombank", "province": "TP.HCM"}
    want = {"bank": "Techcombank", "branch": "Tân Bình", "province": "TP.HCM"}
    result = compare_parts(("bank", "branch", "province"), got, want)
    assert "bank" in result.note
    assert "branch" in result.note
```

- [ ] **Step 2: Run it red**

```bash
cd server && python3 -m pytest compare_parts_test.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'compare_parts'`.

- [ ] **Step 3: Implement**

```python
# server/compare_parts.py
"""Compare a value that is made of several named parts.

#08 is bank + branch + province. #13 is amount basis + term + term start +
method + account. #27 is five company details. The criteria have declared these
in `parts=(...)` from the beginning and nothing has ever read them, so those
cells could only ever say "chưa kiểm tra được".

The distinction that matters: a part that is ABSENT is not the same finding as a
part that DISAGREES. The first sends the reviewer looking, the second sends them
comparing. Collapsing them into one "not ok" throws away the more useful half.
"""
from __future__ import annotations

import enum
import re
import unicodedata
from dataclasses import dataclass


class PartsVerdict(enum.Enum):
    MATCH = "match"
    INCOMPLETE = "incomplete"   # every part read agrees, but some were not found
    MISMATCH = "mismatch"       # at least one part disagrees
    UNKNOWN = "unknown"         # nothing read, or nothing to compare against


@dataclass(frozen=True)
class PartsResult:
    verdict: PartsVerdict
    missing: tuple[str, ...]
    differing: tuple[str, ...]
    note: str


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", text).strip().lower()


def compare_parts(
    parts: tuple[str, ...],
    got: dict[str, str],
    want: dict[str, str],
) -> PartsResult:
    """Compare `got` against `want` over `parts`.

    `UNKNOWN` when nothing was read or there is nothing to compare against --
    never `MISMATCH`, because "I could not see it" and "it is wrong" are
    different claims and only one of them justifies sending a packet back.
    """
    readable = {p for p in parts if _fold(got.get(p))}
    expected = {p for p in parts if _fold(want.get(p))}
    if not readable or not expected:
        return PartsResult(PartsVerdict.UNKNOWN, (), (),
                           "Chưa đọc được nội dung để đối chiếu.")

    comparable = readable & expected
    missing = tuple(p for p in parts if p in expected and p not in readable)
    differing = tuple(p for p in comparable if _fold(got[p]) != _fold(want[p]))

    if differing:
        verdict = PartsVerdict.MISMATCH
    elif missing:
        verdict = PartsVerdict.INCOMPLETE
    else:
        verdict = PartsVerdict.MATCH

    bits = []
    if differing:
        bits.append("Không khớp: " + ", ".join(differing) + ".")
    if missing:
        bits.append("Chưa tìm thấy: " + ", ".join(missing) + ".")
    if verdict is PartsVerdict.MATCH:
        bits.append("Khớp đầy đủ " + str(len(comparable)) + " nội dung.")
    return PartsResult(verdict, missing, differing, " ".join(bits))
```

- [ ] **Step 4: Run green and commit**

```bash
cd server && python3 -m pytest compare_parts_test.py -q
```
Expected: 8 passed.

```bash
git add server/compare_parts.py server/compare_parts_test.py
git commit -m "feat(criteria): compare a value made of several named parts"
```

---

## Task 2: Let the engine use it

**Files:**
- Modify: `server/evaluate.py`
- Modify: `server/evaluate_test.py`

- [ ] **Step 1: Map the four verdicts onto the engine's statuses, and write it down**

Read `server/criteria.py`'s `Status` enum first. The mapping this plan intends:

| PartsVerdict | Status | why |
|---|---|---|
| `MATCH` | `OK` | every part read agrees |
| `MISMATCH` | `NO` | a real disagreement, the reviewer must settle it |
| `INCOMPLETE` | `REVIEW` | not a disagreement, but not a clean pass — a person should look |
| `UNKNOWN` | `PENDING` | the tool could not read it. **Never `NO`.** |

`INCOMPLETE → REVIEW` is the judgement call in this table. State in your report whether it felt
right once you saw real cells, and do not change it silently.

- [ ] **Step 2: Write the failing test**

Add to `server/evaluate_test.py`, in that file's existing style, one test per row of that table for
criterion #08. Follow how the file already builds a packet and evaluates a single criterion — do
not invent a helper.

- [ ] **Step 3: Run red, implement, run green**

In `_compare`'s path, when `criterion.params` carries `parts`, route through `compare_parts` and
map as above. `compare="organisation"` uses the same code — it is a multi-part text comparison
whose expected value comes from reference data, and until #27's reference list exists it will
return `UNKNOWN`, which is correct and honest.

**No existing status may change.** If one does, stop and report.

- [ ] **Step 4: Commit**

```bash
git add server/evaluate.py server/evaluate_test.py
git commit -m "feat(criteria): answer the multi-part criteria instead of skipping them"
```

---

## Task 3: The reader interface, and a fake

Everything downstream must be buildable and testable without a model, a key, or a network.

**Files:**
- Create: `server/semantic_read.py`
- Create: `server/semantic_read_test.py`

- [ ] **Step 1: Write the failing test**

```python
# server/semantic_read_test.py
from semantic_read import FakeReader, SemanticField, read_document


def test_the_fake_returns_what_it_was_given():
    reader = FakeReader({"term": SemanticField(value="15 ngày",
                                               quote="trong vòng 15 ngày kể từ",
                                               page=2)})
    out = read_document(reader, doc_kind="contract", pages_text=["", "", "..."],
                        want=("term",))
    assert out["term"].value == "15 ngày"
    assert out["term"].page == 2


def test_a_field_without_a_quote_is_dropped():
    """A value with nothing to check it against is worse than no value: it turns
    a `?` the reviewer distrusts into a claim they cannot falsify."""
    reader = FakeReader({"term": SemanticField(value="15 ngày", quote="", page=1)})
    out = read_document(reader, doc_kind="contract", pages_text=["a"], want=("term",))
    assert "term" not in out


def test_a_field_the_caller_did_not_ask_for_is_dropped():
    """The model will volunteer things. Only what a criterion asked for is
    allowed through, or the manifest fills with unvalidated extras."""
    reader = FakeReader({"term": SemanticField("15 ngày", "trong vòng 15", 1),
                         "mood": SemanticField("cheerful", "quite cheerful", 1)})
    out = read_document(reader, doc_kind="contract", pages_text=["x"], want=("term",))
    assert set(out) == {"term"}


def test_a_reader_that_raises_yields_nothing_rather_than_failing_the_read():
    """An ingest that dies because a model timed out loses the 13 minutes of
    OCR that already succeeded. Degrade to `pending`, which is honest."""
    class Boom:
        def read(self, **kwargs):
            raise RuntimeError("timeout")

    assert read_document(Boom(), doc_kind="contract", pages_text=["x"],
                         want=("term",)) == {}
```

- [ ] **Step 2: Run red, then implement**

```python
# server/semantic_read.py
"""Read values out of a document that no pattern can find.

Six criteria need a sentence understood rather than a label matched: which of a
dozen dates is the start date (#10, #11), the five details inside a payment
clause (#13), what work was done for which programme (#09), a bank's name,
branch and province out of one line (#08).

Two rules this module exists to enforce:

1. **A value must carry a verbatim quote and a page**, or it is dropped. The
   tool's premise is that it points and a person decides; a value with nothing
   to check it against converts a `?` into an unfalsifiable claim.
2. **A failing reader never fails the ingest.** OCR has already spent minutes by
   this point. A model that times out degrades those cells to `pending`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SemanticField:
    """One value, with the evidence needed to check it."""

    value: str
    #: Verbatim from the page, so it can be found again and boxed.
    quote: str
    page: int


class Reader(Protocol):
    def read(self, *, doc_kind: str, pages_text: list[str],
             want: tuple[str, ...]) -> dict[str, SemanticField]:
        ...


class FakeReader:
    """A reader that returns a fixed answer. Everything downstream of this
    module is testable without a model, a key or a network call."""

    def __init__(self, answers: dict[str, SemanticField]):
        self._answers = answers

    def read(self, *, doc_kind: str, pages_text: list[str],
             want: tuple[str, ...]) -> dict[str, SemanticField]:
        return dict(self._answers)


def read_document(reader, *, doc_kind: str, pages_text: list[str],
                  want: tuple[str, ...]) -> dict[str, SemanticField]:
    """`{field: SemanticField}`, keeping only what was asked for and can be
    checked. Never raises."""
    try:
        raw = reader.read(doc_kind=doc_kind, pages_text=pages_text, want=want)
    except Exception:
        return {}
    return {
        name: field
        for name, field in (raw or {}).items()
        if name in want and field and field.value and field.quote
    }
```

- [ ] **Step 3: Run green and commit**

```bash
cd server && python3 -m pytest semantic_read_test.py -q
git add server/semantic_read.py server/semantic_read_test.py
git commit -m "feat(semantic): a reader interface with a fake, and the quote rule"
```

---

## Task 4: Turn a quote into a box on the page

The model returns text. The viewer highlights rectangles. And the words are gone after ingest, so
this has to run during it.

**Files:**
- Modify: `server/semantic_read.py`
- Modify: `server/semantic_read_test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_quote_is_located_against_the_words_on_that_page():
    words = [
        {"text": "trong", "page": 2, "x": 40, "y": 500, "w": 50, "h": 14},
        {"text": "vòng",  "page": 2, "x": 95, "y": 500, "w": 45, "h": 14},
        {"text": "15",    "page": 2, "x": 145, "y": 500, "w": 20, "h": 14},
        {"text": "ngày",  "page": 2, "x": 170, "y": 500, "w": 45, "h": 14},
    ]
    box = locate_quote("vòng 15 ngày", words, page=2)
    assert box == {"x": 95, "y": 500, "w": 120, "h": 14}


def test_a_quote_on_another_page_is_not_matched():
    words = [{"text": "vòng", "page": 1, "x": 10, "y": 10, "w": 40, "h": 14}]
    assert locate_quote("vòng", words, page=2) is None


def test_a_quote_that_cannot_be_found_gives_no_box_rather_than_a_wrong_one():
    """A highlight over the wrong text is worse than none -- it tells the
    reviewer the tool found something it did not. The value survives without
    a box; the cell simply says the position is unknown."""
    words = [{"text": "hello", "page": 0, "x": 0, "y": 0, "w": 40, "h": 14}]
    assert locate_quote("15 ngày", words, page=0) is None


def test_locating_ignores_accents_and_spacing_like_the_rest_of_the_engine():
    words = [{"text": "trong", "page": 0, "x": 0, "y": 0, "w": 40, "h": 14},
             {"text": "vong",  "page": 0, "x": 45, "y": 0, "w": 40, "h": 14}]
    assert locate_quote("trong vòng", words, page=0) is not None
```

- [ ] **Step 2: Implement `locate_quote(quote, words, page)`**

Fold both sides (reuse `compare_parts._fold` — do not write a third copy), slide a window over that
page's words in reading order, and return the union box of the matching run. Return `None` on no
match. A partial match is not a match.

- [ ] **Step 3: Run green and commit**

```bash
cd server && python3 -m pytest semantic_read_test.py -q
git add server/semantic_read.py server/semantic_read_test.py
git commit -m "feat(semantic): find a quoted phrase among a page's words"
```

---

## Task 5: Wire it into the read, with the fake

**Files:**
- Modify: `server/ocr_extract.py`
- Modify: `server/ocr_extract_test.py`

- [ ] **Step 1: Decide which fields each document is asked for, in `criteria.py`**

The criteria already know. #13's `parts` are exactly the fields to request from a contract. Put the
request list where the criterion lives, not in `ocr_extract.py`.

- [ ] **Step 2: Write the failing test using `FakeReader`**

The whole point of Task 3: this test passes a `FakeReader` into `ocr_packet` and asserts the
manifest gains the value, its quote, its page, and its box — with **no model and no network**.

```python
def test_a_semantic_value_reaches_the_manifest_with_its_evidence():
    # ocr_packet(..., semantic_reader=FakeReader({...})) over a packet whose
    # contract page 2 contains the quoted phrase, then:
    field = next(f for f in result["folder"]["fields"] if f["key"] == "term")
    source = field["sources"][0]
    assert source["value"] == "15 ngày"
    assert source["provenance"] == "llm"
    assert source["page"] == 2
    assert source["bbox"] is not None
```

- [ ] **Step 3: Implement**

`ocr_packet` takes `semantic_reader=None` and skips the whole step when it is `None` — so nothing
changes for anyone who does not opt in. When given one: call `read_document`, locate each quote,
and write the fields with `provenance: "llm"`.

`"llm"` is a new provenance value. `Evidence`'s docstring in `server/evaluate.py` lists the set
(`"ocr" | "idp" | "roster" | "override"`) — add it there too, or the next reader of that file is
misled.

- [ ] **Step 4: Run the whole suite and commit**

```bash
cd server && python3 -m pytest -q
git add server/ocr_extract.py server/ocr_extract_test.py server/criteria.py server/evaluate.py
git commit -m "feat(semantic): record semantic values, with quote and box, at ingest"
```

---

## Task 6: The real adapter — #13 only

**Stop and read.** Everything above works with no model. This task adds one, and it is the only
task whose output cannot be judged by a test. Its purpose is to make **one** criterion answerable on
**real** contracts so somebody with the data can say whether it is good enough.

**Files:**
- Create: `server/semantic_maas.py`
- Create: `server/semantic_maas_test.py`

- [ ] **Step 1: Find out what the account offers**

```bash
cd server && export GREENNODE_API_KEY=...   # the same key the card reader uses
python3 list_models.py
```

**Report the output.** Do not hard-code a model name you have not seen listed. If you have no key,
stop here and say so — Tasks 1–5 stand on their own and this one is not worth guessing at.

- [ ] **Step 2: Write the tests that do not need the network**

Test the request body it builds and the parsing of a canned response — never a live call. Follow
`server/idp_words_test.py`, which already tests a sibling service this way with an injected
transport.

Assert at minimum: the prompt asks for a verbatim quote per field; a response missing a quote is
dropped (Task 3 already enforces this, so assert it survives the adapter); malformed JSON yields
`{}` rather than raising; and the key is read from the environment and never logged.

- [ ] **Step 3: Implement**

A `urllib` POST to `/chat/completions` on `GREENNODE_MAAS_URL` (default the base in
`list_models.py`), asking for JSON with one object per requested field:
`{"field": {"value": ..., "quote": ..., "page": n}}`. Reuse `GREENNODE_API_KEY`.

Opt-in exactly like the card reader: **no model call unless the variables are set.** Absent
credentials means these cells stay `pending`, which is today's behaviour.

Send only the pages of the document being read, as text — not the whole submission, and not images.

- [ ] **Step 4: Run one real contract past it, and report honestly**

For #13's five parts, on a handful of real contracts, report: how many parts came back, how many
quotes located successfully, and every case where the value looked right but the quote could not be
found — that last number decides whether this approach is viable at all.

**Do not tune the prompt against a single contract until the numbers look good.** Report what the
first honest attempt produced.

- [ ] **Step 5: Commit**

```bash
git add server/semantic_maas.py server/semantic_maas_test.py
git commit -m "feat(semantic): read a payment clause via the MaaS endpoint, opt-in"
```

---

## When you are done

Say plainly:

- whether `INCOMPLETE → REVIEW` felt right once you saw real cells
- what `list_models.py` listed, and which model you used
- for #13: parts returned, quotes located, and values whose quote could not be found
- what you did NOT do, and why
- that Tasks 5–6 need a re-ingest before anything shows on an existing case
