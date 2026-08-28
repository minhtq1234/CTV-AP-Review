# Template-Aware Workbook Reading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read both known submission templates — the July pair (`roster.xlsx` + `cccd.xlsx`) and the PUBGm combined workbook (one file, sheets `CTV` / `CCCD` / `MST`) — by inferring structure from headers, and refuse an upload whose bảng kê sheet is missing the columns without which nothing works.

**Architecture:** Three small pure additions, each with its own tests, wired into two existing seams. `select_roster_sheet` replaces `workbook.active`; a column-presence check joins the existing `preflight_roster_workbook`; `classify_image_columns` reads a sheet's header row to learn which columns hold which kind of image, and the existing proximity pairing stays as the fallback for workbooks with no image headers.

**Tech Stack:** Python 3 · openpyxl · pytest. No frontend change.

**Scope note:** the cell-to-document popup is a separate plan — `2026-08-28-cell-to-document.md`. The two share no code and can be done in either order.

---

## Before you start — read this, it will save you a day

**You do not have the data this was measured on, and you cannot get it.** `server/data/` is
gitignored and holds real identity documents — names, CCCD numbers, bank accounts, ID card scans.
Every number quoted below was measured by the author against that data. **Task 1 builds a
synthetic workbook** so you can develop and test the whole plan without it. Nothing in this plan
requires real data to implement or to verify.

**This repo has three divergent lineages that share filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`. A
measurement taken on `main` says nothing here.

**Environment quirks observed on the author's machine** — check whether they apply to yours before
assuming a command is broken:

- the `npm` and `npx` wrappers throw `EPERM: uv_cwd`; call `node_modules/.bin/…` directly
- pytest must run with `server/` as the cwd, because modules there import by bare name
- `zsh` eats unquoted glob-ish arguments: `--include=*.py` must be quoted

**Green before every commit:** `cd server && python3 -m pytest`. At the time of writing that is
**787 passing**, which includes work from a parallel session in `server/app_test.py`; if your
baseline differs, establish it before you start and compare against your own number, not this one.

---

## The two templates

| | July (`Danh Tướng 3Q`) | PUBGm Esports |
|---|---|---|
| bảng kê | `roster.xlsx`, single sheet `Thông tin CK` | sheet `CTV` of a combined workbook, header on **row 6** |
| card images | separate `cccd.xlsx` | sheet `CCCD`, cols D (front) and E (back) |
| bank screenshots | — | sheet `CCCD`, col G, under header `STK` |
| tax screenshots | — | sheet `MST`, col D |

Two facts that decide the design, both measured:

1. **`roster_checks.locate_columns` already reads both.** On the PUBGm `CTV` sheet it finds the
   header on row 6 and maps 13 columns — account, bank, cccd, commitment, dob, gender, gross, mst,
   name, net, period, pit, stt — and parses 25 people. No template-specific code exists or is
   needed for the roster half. **Do not add any.**
2. **`D1:E1` on the `CCCD` sheet is a merged cell labelled `Hình CCCD`.** The header states which
   columns hold the card sides. Image layout is inferable the same way the roster columns already
   are.

## The bug this fixes

`server/roster_workbook.py:104` takes `workbook.active` — the sheet that happened to be selected
when the submitter last saved the file. **Measured on the PUBGm workbook, `active` is `CCCD`, not
`CTV`.** Fed in today, that does not raise: it parses 25 people carrying only name, CCCD and STT,
and every money and identity criterion silently has nothing to compare against. The July template
has one sheet, so the assumption was correct until a multi-sheet template arrived.

---

## What this plan closes in `docs/ver3-scope.md` §3

§3 decided that bảng kê validation stays in the Excel column of the matrix rather than becoming a
new screen, and named what was still missing. Checked against this checkout while writing:

| §3 gap | where it is closed |
|---|---|
| a wrong-sheet read looks exactly like a normal absence | **Task 4** — refuse the upload, naming the sheet read and the columns missing |
| "whatever the second template needs now that it fills different columns" | **Tasks 2, 3, 5, 6** |
| "the PIT rule (#15)" | **already implemented — no task** |

That last row is a correction to §3, not an omission from this plan. `server/evaluate.py:612`
`_pit_basis` already runs the rule: PIT of 0 with a cam kết is OK, PIT of 0 without one is NO, and a
non-zero PIT is PENDING with the reason stated in the cell. What it deliberately does **not** do is
hard-code a rate or a threshold — the code comment at `server/criteria.py:220` says so outright, and
§7 of the checklist puts the applicable rate with Acc rather than in the tool. There is no
implementation task here; there is a question for Acc about whether they want the rate in the tool
at all. **Do not add one on your own initiative.**

---

## File Structure

| File | Responsibility |
|---|---|
| `server/workbook_layout.py` **(create)** | Pure: choose the bảng kê sheet by content; classify a sheet's image columns by header. No IO, no openpyxl objects in the signatures — takes rows and header values, returns decisions. |
| `server/workbook_layout_test.py` **(create)** | Unit tests for both, plus the fixture-built workbook. |
| `server/test_fixtures/combined_workbook.py` **(create)** | Builds a synthetic PUBGm-shaped workbook. PII-free, committed, used by tests. |
| `server/roster_workbook.py` **(modify)** | `load_roster_rows` selects the sheet by content; `preflight_roster_workbook` refuses a sheet missing the required columns. |
| `server/cccd_workbook.py` **(modify)** | Extraction records each drawing's column so the kind can be resolved; unchanged where no headers exist. |
| `server/cccd_pairing.py` **(modify)** | Pair by declared kind when known; keep proximity pairing as the fallback. |

---

## Task 1: A synthetic workbook to develop against

Everything after this depends on having a PUBGm-shaped file that contains no personal data.

**Files:**
- Create: `server/test_fixtures/__init__.py` (empty)
- Create: `server/test_fixtures/combined_workbook.py`

- [ ] **Step 1: Write the builder**

```python
# server/test_fixtures/combined_workbook.py
"""A synthetic workbook shaped like the PUBGm submission template.

Real submissions are identity documents and are never committed. This builds a
file with the same *structure* -- three sheets, a merged image header spanning
two columns, three populations of image in known columns -- carrying invented
names and numbers, so the layout logic can be developed and tested without any
real data.
"""
from __future__ import annotations

import io

import openpyxl
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

#: Invented people. Sequential numbers, obviously not real.
PEOPLE = [
    ("NGUYEN VAN MOT", "001100000001", "8000000001"),
    ("TRAN THI HAI", "001100000002", "8000000002"),
    ("LE VAN BA", "001100000003", "8000000003"),
]


def _png(color: tuple[int, int, int]) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(buf, format="PNG")
    buf.seek(0)
    return buf


def build(path: str, *, active_sheet: str = "CCCD") -> str:
    """Write the workbook to `path` and return it.

    `active_sheet` defaults to `CCCD` on purpose: that is what the real file
    does, and it is the condition that makes `workbook.active` pick the wrong
    sheet. Tests rely on this default to reproduce the bug.
    """
    wb = openpyxl.Workbook()
    ctv = wb.active
    ctv.title = "CTV"

    # Header block above the table, as the real template has.
    ctv["A1"] = "THANH TOÁN DỊCH VỤ"
    ctv["A2"] = "Mã eform plan:"
    ctv["A3"] = "Mã eform thanh toán:"
    headers = ["STT", "Họ và tên", "CCCD/ PP", "MST", "Ngày/ tháng/ năm sinh",
               "Giới tính", "Số tài khoản", "Ngân hàng", "Gross", "Thuế PIT", "Thực Nhận"]
    for col, text in enumerate(headers, start=1):
        ctv.cell(row=5, column=col, value=text)
    for i, (name, cccd, mst) in enumerate(PEOPLE):
        r = 7 + i
        ctv.cell(r, 1, i + 1)
        ctv.cell(r, 2, name)
        ctv.cell(r, 3, cccd)
        ctv.cell(r, 4, mst)
        ctv.cell(r, 5, "01/01/1990")
        ctv.cell(r, 6, "NAM")
        ctv.cell(r, 7, "0123456789")
        ctv.cell(r, 8, "Ngân hàng Thử Nghiệm")
        ctv.cell(r, 9, 8000000)
        ctv.cell(r, 10, 0)
        ctv.cell(r, 11, 8000000)

    cccd_sheet = wb.create_sheet("CCCD")
    for col, text in enumerate(["STT", "Họ tên", "Số CCCD", "Hình CCCD", None, "STK", "Hình Ảnh"],
                               start=1):
        if text is not None:
            cccd_sheet.cell(row=1, column=col, value=text)
    # The header that makes the layout self-describing: one label over two columns.
    cccd_sheet.merge_cells("D1:E1")
    for i, (name, cccd, _) in enumerate(PEOPLE):
        r = 2 + i
        cccd_sheet.cell(r, 1, i + 1)
        cccd_sheet.cell(r, 2, name)
        cccd_sheet.cell(r, 3, cccd)
        cccd_sheet.cell(r, 6, "0123456789 - Ngân hàng Thử Nghiệm")
        cccd_sheet.add_image(XLImage(_png((200, 30, 30))), f"D{r}")   # front
        cccd_sheet.add_image(XLImage(_png((30, 30, 200))), f"E{r}")   # back
        cccd_sheet.add_image(XLImage(_png((30, 200, 30))), f"G{r}")   # bank screenshot

    mst_sheet = wb.create_sheet("MST")
    for col, text in enumerate(["STT", "Họ tên", "MST", "Hình Ảnh"], start=1):
        mst_sheet.cell(row=1, column=col, value=text)
    for i, (name, _, mst) in enumerate(PEOPLE):
        r = 2 + i
        mst_sheet.cell(r, 1, i + 1)
        mst_sheet.cell(r, 2, name)
        mst_sheet.cell(r, 3, mst)
        mst_sheet.add_image(XLImage(_png((200, 200, 30))), f"D{r}")

    wb.active = wb.sheetnames.index(active_sheet)
    wb.save(path)
    return path


def build_july(path: str) -> str:
    """The other template: one sheet, no images, header on row 1."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Thông tin CK"
    for col, text in enumerate(["STT", "Họ và tên", "CCCD", "MST", "Số tài khoản",
                                "Gross", "Thuế PIT", "Thực Nhận"], start=1):
        ws.cell(row=1, column=col, value=text)
    for i, (name, cccd, mst) in enumerate(PEOPLE):
        r = 2 + i
        ws.cell(r, 1, i + 1); ws.cell(r, 2, name); ws.cell(r, 3, cccd); ws.cell(r, 4, mst)
        ws.cell(r, 5, "0123456789"); ws.cell(r, 6, 8000000); ws.cell(r, 7, 0); ws.cell(r, 8, 8000000)
    wb.save(path)
    return path
```

- [ ] **Step 2: Prove the fixture reproduces the bug**

```python
# server/workbook_layout_test.py
import os
import tempfile

import openpyxl

from test_fixtures.combined_workbook import build, build_july


def test_the_fixture_reproduces_the_active_sheet_trap():
    """The real PUBGm file is saved with CCCD selected. If the fixture did not
    do the same, every test below would pass for the wrong reason."""
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["CTV", "CCCD", "MST"]
    assert wb.active.title == "CCCD"          # NOT the bảng kê


def test_the_fixture_has_a_merged_image_header():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    ws = openpyxl.load_workbook(path)["CCCD"]
    merged = {str(r) for r in ws.merged_cells.ranges}
    assert "D1:E1" in merged
    assert ws["D1"].value == "Hình CCCD"


def test_the_july_fixture_is_single_sheet():
    path = build_july(os.path.join(tempfile.mkdtemp(), "roster.xlsx"))
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Thông tin CK"]
```

- [ ] **Step 3: Run them**

```bash
cd server && python3 -m pytest workbook_layout_test.py -v
```
Expected: PASS (3 passed)

- [ ] **Step 4: Commit**

```bash
git add server/test_fixtures/__init__.py server/test_fixtures/combined_workbook.py server/workbook_layout_test.py
git commit -m "test(workbook): a synthetic workbook shaped like the combined template"
```

---

## Task 2: Choose the bảng kê sheet by what it contains

**Files:**
- Create: `server/workbook_layout.py`
- Modify: `server/workbook_layout_test.py`

- [ ] **Step 1: Write the failing test**

```python
# append to server/workbook_layout_test.py
import openpyxl
from workbook_layout import score_roster_sheet, select_roster_sheet


def _rows(path, sheet):
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_the_ctv_sheet_outscores_its_neighbours():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    scores = {name: score_roster_sheet(_rows(path, name)) for name in ("CTV", "CCCD", "MST")}
    assert scores["CTV"] > scores["CCCD"]
    assert scores["CTV"] > scores["MST"]


def test_select_picks_ctv_even_though_cccd_is_the_active_sheet():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    wb = openpyxl.load_workbook(path, data_only=True)
    sheets = {name: _rows(path, name) for name in wb.sheetnames}
    assert wb.active.title == "CCCD"            # the trap
    assert select_roster_sheet(sheets) == "CTV"  # what we want instead


def test_select_on_a_single_sheet_workbook_picks_that_sheet():
    path = build_july(os.path.join(tempfile.mkdtemp(), "roster.xlsx"))
    sheets = {"Thông tin CK": _rows(path, "Thông tin CK")}
    assert select_roster_sheet(sheets) == "Thông tin CK"


def test_select_returns_none_when_no_sheet_looks_like_a_roster():
    assert select_roster_sheet({"Sheet1": [["hello"], ["world"]]}) is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd server && python3 -m pytest workbook_layout_test.py -k roster -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'workbook_layout'`

- [ ] **Step 3: Implement**

```python
# server/workbook_layout.py
"""Which sheet is the bảng kê, and which columns hold which images.

Both answers come from the sheet's own headers rather than from a per-template
declaration. `roster_checks.locate_columns` already reads two different
templates unaided; this applies the same idea to the two things it does not
cover -- choosing a sheet in a multi-sheet workbook, and finding the image
columns.

Pure: takes rows and header values, returns decisions. No openpyxl objects
cross these signatures, so every branch is testable without a file.
"""
from __future__ import annotations

import roster_checks

#: A sheet has to carry these to be usable as a bảng kê at all. Without a name
#: there is nobody to match a packet to; without a CCCD there is no identity to
#: match on; without a money column there is nothing to pay.
REQUIRED_COLUMNS = ("name", "cccd")
MONEY_COLUMNS = ("gross", "net", "pit")


def score_roster_sheet(rows: list[list]) -> int:
    """How much like a bảng kê this sheet looks, as a count of mapped columns.

    Deliberately a plain count rather than a weighted rule: the sheet that maps
    the most known columns is the roster, and every template we have seen makes
    that unambiguous by a wide margin (the PUBGm `CTV` sheet maps 13; its
    `CCCD` and `MST` sheets map 3 each).
    """
    try:
        columns, _ = roster_checks.locate_columns(rows)
    except Exception:
        return 0
    return len(columns or {})


def select_roster_sheet(sheets: dict[str, list[list]]) -> str | None:
    """The name of the sheet to read as the bảng kê, or None if none qualifies.

    Ties break on workbook order, which is the order `sheets` is given in.
    """
    best_name, best_score = None, 0
    for name, rows in sheets.items():
        score = score_roster_sheet(rows)
        if score > best_score:
            best_name, best_score = name, score
    if best_name is None:
        return None
    columns, _ = roster_checks.locate_columns(sheets[best_name])
    if not all(key in (columns or {}) for key in REQUIRED_COLUMNS):
        return None
    return best_name


def missing_required_columns(rows: list[list]) -> list[str]:
    """Which of the columns nothing works without are absent from this sheet.

    Returns `["money"]` for the money group rather than naming all three, since
    a template only needs one of them.
    """
    columns, _ = roster_checks.locate_columns(rows)
    columns = columns or {}
    missing = [key for key in REQUIRED_COLUMNS if key not in columns]
    if not any(key in columns for key in MONEY_COLUMNS):
        missing.append("money")
    return missing
```

- [ ] **Step 4: Run the tests**

```bash
cd server && python3 -m pytest workbook_layout_test.py -v
```
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add server/workbook_layout.py server/workbook_layout_test.py
git commit -m "feat(workbook): choose the bảng kê sheet by content, not by which tab was open"
```

---

## Task 3: Use it, and stop trusting `workbook.active`

**Files:**
- Modify: `server/roster_workbook.py:94-107`
- Modify: `server/workbook_layout_test.py`

- [ ] **Step 1: Write the failing test**

```python
# append to server/workbook_layout_test.py
from roster_workbook import load_roster_rows


def test_load_roster_rows_reads_the_ctv_sheet_not_the_active_one():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    with open(path, "rb") as handle:
        rows = load_roster_rows(handle)
    flat = [str(c) for row in rows for c in row if c is not None]
    # The bảng kê carries MST and a bank name; the CCCD sheet carries neither.
    assert any("MST" in s for s in flat), "read a sheet with no MST column — probably CCCD"
    assert any("Ngân hàng" in s for s in flat)


def test_load_roster_rows_still_reads_a_single_sheet_workbook():
    path = build_july(os.path.join(tempfile.mkdtemp(), "roster.xlsx"))
    with open(path, "rb") as handle:
        rows = load_roster_rows(handle)
    assert any("Họ và tên" in str(c) for row in rows for c in row if c is not None)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd server && python3 -m pytest workbook_layout_test.py -k load_roster_rows -v
```
Expected: FAIL — the first test's assertion, because `workbook.active` returns the `CCCD` sheet, which has no MST column.

- [ ] **Step 3: Implement**

Replace `load_roster_rows` (`server/roster_workbook.py:94-107`) with:

```python
def load_roster_rows(xlsx_source) -> list[list]:
    """Preflight an XLSX, then load the sheet that looks like the bảng kê.

    Not `workbook.active`: that is whichever tab the submitter happened to have
    selected when they saved, and on the combined template it resolves to the
    CCCD sheet -- which parses cleanly with only name, CCCD and STT, leaving
    every money and identity criterion with nothing to compare against, and no
    error anywhere. The sheet is chosen by which one maps the most known
    columns (`workbook_layout.select_roster_sheet`).
    """
    preflight_roster_workbook(xlsx_source)
    _seek_start(xlsx_source)
    workbook = openpyxl.load_workbook(
        xlsx_source,
        read_only=True,
        data_only=True,
    )
    try:
        sheets = {
            name: [list(row) for row in workbook[name].iter_rows(values_only=True)]
            for name in workbook.sheetnames
        }
        chosen = workbook_layout.select_roster_sheet(sheets)
        if chosen is None:
            # Preflight should already have refused this; treat it as a bug
            # rather than silently reading an arbitrary sheet.
            raise RosterWorkbookError("no-roster-sheet")
        return sheets[chosen]
    finally:
        workbook.close()
        _seek_start(xlsx_source)
```

Add the import at the top of the file, beside the existing ones:

```python
import workbook_layout
```

**Note on cost:** this reads every sheet rather than one. The largest workbook seen is 18 MB with
three sheets; `read_only=True` streams, so this is bounded. If a future template has many large
sheets, score them lazily and stop at the first that maps all required columns.

- [ ] **Step 4: Run the tests**

```bash
cd server && python3 -m pytest workbook_layout_test.py -v && python3 -m pytest -q
```
Expected: the new file passes; the full suite stays at your established baseline.

- [ ] **Step 5: Commit**

```bash
git add server/roster_workbook.py server/workbook_layout_test.py
git commit -m "fix(workbook): read the bảng kê sheet by content, not workbook.active"
```

---

## Task 4: Refuse an upload whose bảng kê has no usable columns

Without this, a wrong-sheet read is indistinguishable from a normal absence: every Excel cell in
the matrix reports `Bảng kê không có giá trị cho tiêu chí này`, which is character-for-character
what a legitimately unfilled column reports. The reviewer cannot tell a catastrophe from a normal
case, and only finds out after a full processing run.

**Files:**
- Modify: `server/roster_workbook.py` (`preflight_roster_workbook`, from line 111)
- Modify: `server/workbook_layout_test.py`

- [ ] **Step 1: Write the failing test**

```python
# append to server/workbook_layout_test.py
import openpyxl as _openpyxl
import pytest

from roster_workbook import RosterWorkbookError, preflight_roster_workbook
from workbook_layout import missing_required_columns


def _workbook_with_only(path, headers):
    wb = _openpyxl.Workbook()
    ws = wb.active
    for col, text in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=text)
    ws.cell(row=2, column=1, value=1)
    wb.save(path)
    return path


def test_missing_required_columns_names_what_is_absent():
    rows = [["STT", "Họ tên", "Số CCCD"], [1, "NGUYEN VAN MOT", "001100000001"]]
    assert missing_required_columns(rows) == ["money"]
    rows_no_name = [["STT", "Số CCCD"], [1, "001100000001"]]
    assert "name" in missing_required_columns(rows_no_name)


def test_preflight_refuses_a_workbook_with_no_usable_roster_sheet():
    path = _workbook_with_only(os.path.join(tempfile.mkdtemp(), "bad.xlsx"),
                               ["STT", "Họ tên", "Số CCCD"])
    with open(path, "rb") as handle:
        with pytest.raises(RosterWorkbookError) as caught:
            preflight_roster_workbook(handle)
    assert "roster" in str(caught.value)


def test_preflight_accepts_both_real_templates():
    for builder in (build, build_july):
        path = builder(os.path.join(tempfile.mkdtemp(), "ok.xlsx"))
        with open(path, "rb") as handle:
            preflight_roster_workbook(handle)     # must not raise
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd server && python3 -m pytest workbook_layout_test.py -k preflight -v
```
Expected: FAIL — `preflight_roster_workbook` accepts the bad workbook, so `pytest.raises` gets nothing.

- [ ] **Step 3: Implement**

At the end of `preflight_roster_workbook`, after the existing container and XML validation
succeeds, add the column check. Keep it last: the cheap structural checks should still fail first.

```python
    # The container is sound. Now: is any sheet usable as a bảng kê? A workbook
    # that parses but has no name/CCCD/money column produces a case where every
    # comparison silently has nothing to compare against, and the reviewer only
    # finds out after a full run.
    _seek_start(xlsx_source)
    workbook = openpyxl.load_workbook(xlsx_source, read_only=True, data_only=True)
    try:
        sheets = {
            name: [list(row) for row in workbook[name].iter_rows(values_only=True)]
            for name in workbook.sheetnames
        }
    finally:
        workbook.close()
        _seek_start(xlsx_source)

    chosen = workbook_layout.select_roster_sheet(sheets)
    if chosen is None:
        best = max(sheets, key=lambda n: workbook_layout.score_roster_sheet(sheets[n]),
                   default=None)
        missing = workbook_layout.missing_required_columns(sheets[best]) if best else ["name", "cccd", "money"]
        raise RosterWorkbookError(
            f"no-roster-sheet: read '{best}', missing {', '.join(missing)}"
        )
```

- [ ] **Step 4: Run the tests**

```bash
cd server && python3 -m pytest workbook_layout_test.py -v && python3 -m pytest -q
```
Expected: the new file passes; the full suite stays at baseline.

- [ ] **Step 5: Check the message reaches the user**

The error surfaces through `POST /api/cases`. Find where `RosterWorkbookError` is caught in
`server/app.py` and confirm its message reaches the response body rather than being flattened to a
generic failure. If it is flattened, widen it — the whole point of this task is that the reviewer
learns *which sheet was read and what was missing*. Report what you found either way.

- [ ] **Step 6: Commit**

```bash
git add server/roster_workbook.py server/workbook_layout_test.py
git commit -m "feat(workbook): refuse an upload whose bảng kê has no usable columns"
```

---

## Task 5: Learn which columns hold which images

**Files:**
- Modify: `server/workbook_layout.py`
- Modify: `server/workbook_layout_test.py`

- [ ] **Step 1: Write the failing test**

```python
# append to server/workbook_layout_test.py
from workbook_layout import classify_image_columns


def test_a_merged_header_covers_both_card_columns():
    # "Hình CCCD" merged across D:E -- one label, two columns, front and back.
    header = {3: "Hình CCCD", 4: "Hình CCCD", 5: "STK", 6: "Hình Ảnh"}
    kinds = classify_image_columns(header, sheet_name="CCCD")
    assert kinds[3] == "card"
    assert kinds[4] == "card"


def test_an_image_column_beside_stk_is_a_bank_screenshot():
    header = {3: "Hình CCCD", 4: "Hình CCCD", 5: "STK", 6: "Hình Ảnh"}
    kinds = classify_image_columns(header, sheet_name="CCCD")
    assert kinds[6] == "bank"


def test_an_image_column_on_an_mst_sheet_is_a_tax_screenshot():
    header = {0: "STT", 1: "Họ tên", 2: "MST", 3: "Hình Ảnh"}
    kinds = classify_image_columns(header, sheet_name="MST")
    assert kinds[3] == "tax"


def test_a_sheet_with_no_image_headers_classifies_nothing():
    assert classify_image_columns({0: "STT", 1: "Họ và tên"}, sheet_name="Thông tin CK") == {}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd server && python3 -m pytest workbook_layout_test.py -k image_column -v
```
Expected: FAIL — `cannot import name 'classify_image_columns'`

- [ ] **Step 3: Implement**

```python
# add to server/workbook_layout.py
from ocr_extract import norm

#: What an image column can hold. `card` is the only kind the pipeline consumes
#: today; `bank` and `tax` are recognised so they are never mistaken for a card
#: side, and are available to the criteria that will want them (#8, #6).
CARD, BANK, TAX = "card", "bank", "tax"

_CARD_HEADERS = ("hinh cccd", "anh cccd", "hinh the")
_ANY_IMAGE_HEADERS = ("hinh anh", "hinh", "anh")


def classify_image_columns(header: dict[int, str], sheet_name: str) -> dict[int, str]:
    """Column index -> what kind of image it holds, read from the header row.

    A merged header cell reports the same text for every column it spans, which
    is what tells us `Hình CCCD` over D:E means front and back rather than one
    image. A generic `Hình Ảnh` takes its meaning from its neighbour: beside a
    `STK` column it is a bank screenshot; on a sheet keyed by MST it is a tax
    lookup. Anything unrecognised is left out rather than guessed at -- an
    unclassified image is better than an image filed as the wrong kind.
    """
    flat = {index: norm(str(text or "")) for index, text in header.items()}
    kinds: dict[int, str] = {}
    for index, text in flat.items():
        if not text:
            continue
        if any(marker in text for marker in _CARD_HEADERS):
            kinds[index] = CARD
            continue
        if any(marker in text for marker in _ANY_IMAGE_HEADERS):
            left = flat.get(index - 1, "")
            if "stk" in left or "tai khoan" in left:
                kinds[index] = BANK
            elif "mst" in norm(sheet_name) or "mst" in left:
                kinds[index] = TAX
    return kinds
```

- [ ] **Step 4: Run the tests**

```bash
cd server && python3 -m pytest workbook_layout_test.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/workbook_layout.py server/workbook_layout_test.py
git commit -m "feat(workbook): read image column kinds from the header row"
```

---

## Task 6: Carry the column through extraction, and pair only within a kind

The extractor already records each drawing's anchor, which includes its column
(`cccd_workbook.py`, `Anchor`, around line 173). Pairing then associates a front with a back by
anchor proximity (`cccd_pairing.py`). With three image populations two columns apart, proximity
will pair a card front with a bank screenshot.

**Files:**
- Modify: `server/cccd_workbook.py`
- Modify: `server/cccd_pairing.py`
- Modify: `server/cccd_pairing_test.py`

- [ ] **Step 1: Read before you change**

Read `cccd_workbook.extract_drawings` and `cccd_pairing`'s entry point in full and write down, in
your report, the exact structure a drawing record has today and where the pairing decision is
made. Do not skip this: the plan's author read them but did not write the pairing code out here,
and a guess at that structure is how this task goes wrong.

- [ ] **Step 2: Write the failing test**

Add a test to `server/cccd_pairing_test.py` in the style of the ones already there, asserting that
a front in a `card` column is **not** paired with an image in a `bank` column, however close the
anchors are. Use the fixture from Task 1 if it is convenient, or hand-built records matching the
structure you documented in Step 1.

- [ ] **Step 3: Run it to verify it fails**

```bash
cd server && python3 -m pytest cccd_pairing_test.py -v
```
Expected: FAIL — proximity pairing associates them today.

- [ ] **Step 4: Implement**

Thread the kind through: extraction attaches `kind` to each drawing record using
`classify_image_columns` over the sheet's header row; pairing refuses to associate two drawings of
different kinds, and only considers `card` drawings as sides at all.

**Keep proximity pairing as the fallback.** When `classify_image_columns` returns nothing — which
is exactly the July `cccd.xlsx`, whose sheet has no image headers — every drawing has kind `None`
and today's behaviour must be preserved unchanged. Assert that in a test.

- [ ] **Step 5: Run the tests**

```bash
cd server && python3 -m pytest -q
```
Expected: your established baseline.

- [ ] **Step 6: Commit**

```bash
git add server/cccd_workbook.py server/cccd_pairing.py server/cccd_pairing_test.py
git commit -m "feat(cccd): pair card sides within a kind, never across populations"
```

---

## Task 7: Accept the combined workbook as one upload

**Files:**
- Modify: `server/app.py` (`POST /api/cases`)
- Modify: `server/app_test.py`

- [ ] **Step 1: Check with the plan's author first**

`POST /api/cases` takes `pdf`, `roster` and `cccd` as three separate files. The combined template
is one file serving as both roster and cards. There are two ways to take it and the choice is a
product decision, not an implementation detail:

- the same file is uploaded in both the `roster` and `cccd` fields, and the backend deduplicates
- the upload accepts a single `workbook` field and infers

**Stop here and ask.** Everything before this task stands on its own and is worth committing
without it; this task should not be guessed at.

- [ ] **Step 2: Once decided, write the failing test, implement, and commit**

Follow the same shape as the tasks above: a test against the Task 1 fixture that a single combined
workbook produces both a parsed roster and extracted card drawings, run it red, implement, run it
green, commit.

---

## What you cannot verify locally, and what to do about it

- **Card yield.** With GreenNode IDP configured the July batch auto-matches 39 of 42 cards; on
  local OCR alone it matches 24. You will have neither the credentials nor the cards. Do not treat
  a low match count in your own testing as a regression — assert on *structure* (which drawing was
  classified as which kind, which sheet was read), never on match counts.
- **Segmentation and criteria counts.** Every "N of 41 packets" figure in the docs came from real
  submissions. Your fixture has three invented people.
- **The 51-minute run.** Ingest on a real submission is ~13 minutes of OCR and ~36 minutes of card
  matching. Nothing in this plan needs a full run to verify.

When you are done, say plainly which claims you verified and which you took on trust.
