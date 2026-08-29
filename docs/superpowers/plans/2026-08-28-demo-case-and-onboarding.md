# Demo Case & Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh clone of this repository can be set up from one command list, and can then show a
working case on screen within seconds — without any contractor's real data.

**Architecture:** Two independent pieces. A dependency manifest, which does not exist today. And a
generator that writes a *already-processed* case straight into `server/data/cases/`, skipping the
50-minute read entirely, because the demo's job is to exercise the screens rather than the reader.

**Tech Stack:** Python 3.11+ · Pillow · openpyxl · pytest. No frontend change.

---

## Why this exists

Right now a new developer can run the test suite and nothing else. `server/data/` is gitignored
(it holds real names, ID numbers, bank accounts and scans), so after a successful setup **the case
list is empty** and there is no way to see the screens, click through a review, or demo the tool.
Every UI change is verified by unit tests alone.

There is also no `requirements.txt`. The Python package list exists only because somebody read the
imports and wrote them down by hand in a handbook.

Both are cheap to fix and both block everything after them.

## The decision that keeps this small

**The demo case is seeded already-processed. It is never put through the reader.**

The obvious design — generate a PDF, run the real pipeline over it — drags in a problem with no
cheap answer: the reader OCRs rendered pages with `lang="vie"`, so a synthetic PDF would need real
Vietnamese glyphs, which means finding and licensing a Vietnamese-capable TTF and getting Tesseract
to read it back accurately enough to assert on. That is a rabbit hole, and it buys nothing the demo
needs.

What the demo needs is a case whose **screens** work: a packet list, 25 criteria with a spread of
statuses, documents that open, card images that display. All of that comes from
`case.json` + `packets/N/manifest.json` + page images. So write those directly.

**Explicitly out of scope:** testing the ingest pipeline end to end on synthetic input. Say so in
your report rather than half-building it. If it is wanted later it is its own plan, and its first
task is the font question.

---

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

**Environment quirks observed on the author's machine** — check whether they apply to yours:

- the `npm`/`npx` wrappers throw `EPERM: uv_cwd`; call `node_modules/.bin/...` directly
- **`pytest` must run with `server/` as the working directory** — the modules import each other
  flat (`import roster_checks`), so running from the repo root fails on imports

**Green before every commit:** `cd server && python3 -m pytest -q`. At the time of writing that is
**836 passing** with `cwd=server/` (the earlier figure of 821 was never reproducible here);
establish your own baseline first and compare against it.

**`server/app.py` and `server/app_test.py` are free to change.** They were held back while
another session had uncommitted work in them; that work landed in `7624a3e` on 2026-08-28 and
the tree is clean. Do not stop on this.

---

## File Structure

| File | Responsibility |
|---|---|
| `server/requirements.txt` **(create)** | The Python packages, pinned loosely. |
| `server/test_fixtures/demo_case.py` **(create)** | Builds one synthetic, already-processed case directory. |
| `server/test_fixtures/demo_case_test.py` **(create)** | Asserts the built case is shaped the way the app reads it. |
| `server/seed_demo_case.py` **(create)** | The command a new developer runs: writes the demo case into the store. |

---

## Task 1: The dependency manifest

**Files:**
- Create: `server/requirements.txt`

- [ ] **Step 1: Derive the list from the imports, not from memory**

```bash
cd server
grep -rhoE "^(import|from) [a-zA-Z_][a-zA-Z0-9_]*" *.py | awk '{print $2}' | sort -u
```

Every name in that output is either a standard-library module, a sibling module in this directory,
or a third-party package. The third-party ones at the time of writing are: `fastapi`, `fitz`
(the import name for **PyMuPDF**), `openpyxl`, `PIL` (**Pillow**), `pytesseract`, `pydantic`,
`starlette`, `pytest`. `uvicorn` and `python-multipart` are not imported but are required at
runtime — uvicorn serves the app, and FastAPI needs python-multipart to accept file uploads.

- [ ] **Step 2: Write it**

```
# server/requirements.txt
# Derived from the server's imports plus two runtime-only packages:
# uvicorn (serves the app) and python-multipart (FastAPI needs it to accept
# file uploads). Regenerate the import list with:
#   grep -rhoE "^(import|from) [a-zA-Z_][a-zA-Z0-9_]*" *.py | awk '{print $2}' | sort -u
fastapi>=0.110
uvicorn>=0.27
python-multipart>=0.0.9
pymupdf>=1.24
openpyxl>=3.1
pillow>=10.2
pytesseract>=0.3.10
pytest>=8.0
```

`pydantic` and `starlette` are omitted deliberately: both are FastAPI's own dependencies and
pinning them separately invites a version conflict.

- [ ] **Step 3: Verify it actually installs and the suite still passes**

```bash
cd server && python3 -m pip install -r requirements.txt && python3 -m pytest -q
```
Expected: install succeeds; test count matches your baseline.

**Tesseract itself is not a Python package** and cannot go in this file. It needs the Vietnamese
language data, or every OCR read returns nonsense. Add a line to the file's header comment saying
so, naming `brew install tesseract tesseract-lang` for macOS.

- [ ] **Step 4: Commit**

```bash
git add server/requirements.txt
git commit -m "build: a dependency manifest, derived from the imports"
```

---

## Task 2: A synthetic page image

The demo case needs page images that look enough like paperwork to review. They do not need to be
OCR-able — nothing reads them.

**Files:**
- Create: `server/test_fixtures/demo_case.py`
- Create: `server/test_fixtures/demo_case_test.py`

- [ ] **Step 1: Write the failing test**

```python
# server/test_fixtures/demo_case_test.py
import io

from PIL import Image

from test_fixtures import demo_case


def test_page_image_is_a_readable_png_of_the_requested_size():
    data = demo_case.page_png("HỢP ĐỒNG DỊCH VỤ", ["Bên A: VNG", "Bên B: NGUYEN VAN MOT"],
                              width=1000, height=1400)

    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.size == (1000, 1400)
    # Not a blank sheet: something was drawn.
    assert len(set(image.convert("L").getdata())) > 1


def test_page_image_is_deterministic():
    """The same inputs must give the same bytes, or every rebuild of the demo
    case shows as a change and the fixture stops being a fixture."""
    first = demo_case.page_png("A", ["b"], width=200, height=300)
    second = demo_case.page_png("A", ["b"], width=200, height=300)
    assert first == second
```

- [ ] **Step 2: Run it red**

```bash
cd server && python3 -m pytest test_fixtures/demo_case_test.py -q
```
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: page_png`.

- [ ] **Step 3: Implement**

```python
# server/test_fixtures/demo_case.py
"""Build one synthetic, already-processed case for demos and for developing the
screens against.

Deliberately NOT run through the reader: see the plan's "decision that keeps
this small". Nothing here is OCR'd, so the page images only have to look like
paperwork, and the values come from the manifest this module writes.

Everything is fabricated. No real contractor appears anywhere in it.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

#: Fabricated people. Sequential ID numbers, obviously-synthetic names, so no
#: real identity can be mistaken for one of these.
PEOPLE = [
    {"stt": 1, "name": "NGUYEN VAN MOT",  "cccd": "001100000001",
     "mst": "0011000001", "tk": "1900000001", "dob": "01/01/1990",
     "gender": "Nam", "gross": 8_000_000, "pit": 0,       "net": 8_000_000},
    {"stt": 2, "name": "TRAN THI HAI",    "cccd": "001100000002",
     "mst": "0011000002", "tk": "1900000002", "dob": "02/02/1991",
     "gender": "Nữ",  "gross": 8_888_889, "pit": 888_889, "net": 8_000_000},
    {"stt": 3, "name": "LE VAN BA",       "cccd": "001100000003",
     "mst": "0011000003", "tk": "1900000003", "dob": "03/03/1992",
     "gender": "Nam", "gross": 4_400_000, "pit": 0,       "net": 4_400_000},
]


def _font(size: int) -> ImageFont.ImageFont:
    """A font that renders at the requested size.

    Pillow's default font ignores `size`, which makes every page look the same
    and the headings unreadable. Try the DejaVu that ships with most Pillow
    installs first, then fall back rather than failing the build.
    """
    for name in ("DejaVuSans.ttf", "Arial Unicode.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def page_png(heading: str, lines: list[str], *, width: int, height: int) -> bytes:
    """One page of fabricated paperwork as PNG bytes.

    Deterministic: same arguments, same bytes. A fixture that changes on every
    build is not a fixture.
    """
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    margin = max(24, width // 14)
    draw.text((margin, margin), heading, fill="black", font=_font(max(14, width // 32)))
    draw.line([(margin, margin + height // 22), (width - margin, margin + height // 22)],
              fill="black", width=2)

    y = margin + height // 16
    body = _font(max(11, width // 55))
    for line in lines:
        draw.text((margin, y), line, fill="black", font=body)
        y += height // 26

    # A signature block at the foot, so the six signature criteria have
    # something plausible to point at once they learn how.
    draw.text((margin, height - margin - height // 12), "BÊN CUNG CẤP DỊCH VỤ",
              fill="black", font=body)
    draw.text((width // 2, height - margin - height // 12), "ĐẠI DIỆN VNG",
              fill="black", font=body)

    out = io.BytesIO()
    image.save(out, format="PNG", optimize=False)
    return out.getvalue()
```

- [ ] **Step 4: Run it green, then commit**

```bash
cd server && python3 -m pytest test_fixtures/demo_case_test.py -q
```
Expected: 2 passed.

```bash
git add server/test_fixtures/demo_case.py server/test_fixtures/demo_case_test.py
git commit -m "test(fixtures): synthetic page images for a demo case"
```

---

## Task 3: The case directory

**Files:**
- Modify: `server/test_fixtures/demo_case.py`
- Modify: `server/test_fixtures/demo_case_test.py`

- [ ] **Step 1: Read how a real case is laid out before writing one**

Do not guess the shape. Read these three, and write down in your report what each key is for:

- `server/cases.py` — the `CaseStore`, and what `case.json` must contain
- a real manifest's shape, which is exactly:
  `{"id", "name", "product", "heading", "status", "exempt", "docs": [{"id","kind","label","pages":[{"src","width","height"}]}], "fields": [...]}`
- `src/ctv/types.ts` — `EvidenceKind` is the closed set `id_front | id_back | contract | commitment | pit | bbnt | appendix`

- [ ] **Step 2: Write the failing test**

```python
def test_built_case_is_shaped_the_way_the_app_reads_it(tmp_path):
    case_dir = demo_case.build(str(tmp_path / "demo"))

    import json
    import os

    case = json.loads(open(os.path.join(case_dir, "case.json")).read())
    assert case["status"] == "ready"
    assert len(case["packets"]) == len(demo_case.PEOPLE)
    # Matching is by identity, so every packet must carry one.
    assert all(p["ocrIdentity"]["cccd"] for p in case["packets"])
    assert all(p["matchedBy"] == "cccd" for p in case["packets"])

    manifest = json.loads(
        open(os.path.join(case_dir, "packets", "0", "manifest.json")).read()
    )
    kinds = [d["kind"] for d in manifest["docs"]]
    assert "contract" in kinds and "bbnt" in kinds
    assert all(k in {"id_front", "id_back", "contract", "commitment", "pit",
                     "bbnt", "appendix"} for k in kinds)

    # Every page a doc claims must exist on disk, or the viewer shows nothing.
    for doc in manifest["docs"]:
        for page in doc["pages"]:
            assert os.path.isfile(os.path.join(case_dir, "packets", "0",
                                               os.path.basename(page["src"])))


def test_built_case_contains_no_real_looking_identity(tmp_path):
    """The whole point. Every number is sequential from a fabricated base."""
    case_dir = demo_case.build(str(tmp_path / "demo"))
    import pathlib
    import re

    text = "\n".join(
        p.read_text(errors="ignore")
        for p in pathlib.Path(case_dir).rglob("*.json")
    )
    for number in re.findall(r"\b\d{9,13}\b", text):
        assert number.startswith(("0011", "1900")), f"unexpected identifier {number}"
```

- [ ] **Step 3: Run it red, then implement `build()`**

`build(target_dir)` must:

1. create `target_dir/packets/<n>/` for each person in `PEOPLE`
2. write page PNGs there via `page_png`, named `pg0.png`, `pg1.png`, … — the same naming a real
   packet uses
3. write `manifest.json` per packet with `contract` (2 pages), `bbnt` (1), `appendix` (1),
   `pit` (1), `id_front` (1), `id_back` (1)
4. write the six `fields` entries (`hoten`, `cccd`, `mst`, `tk`, `ngaysinh`, `phi`) with an
   `expected` from `PEOPLE` and a `sources` entry per document — give **packet 2 a deliberate
   one-digit mismatch on `tk`**, so the demo has a red cell to talk about
5. write `case.json` with `status: "ready"`, `summary` counts that agree with the packets, and
   one packet entry each carrying `ocrIdentity`, `rosterIdentity` and `matchedBy: "cccd"`
6. return the directory path

Give at least one packet a missing `appendix` so `na` appears, and leave one field unextracted on
one packet so `pending` appears. A demo where every cell is green teaches nobody anything.

- [ ] **Step 4: Run green and commit**

```bash
cd server && python3 -m pytest test_fixtures/ -q
git add server/test_fixtures/
git commit -m "test(fixtures): build a whole synthetic case, ready to browse"
```

---

## Task 4: The seed command

**Files:**
- Create: `server/seed_demo_case.py`

- [ ] **Step 1: Write it**

```python
# server/seed_demo_case.py
"""Put the synthetic demo case into the local store, so a fresh clone has
something to look at.

    cd server && python3 seed_demo_case.py

Safe to re-run: it replaces the demo case and leaves every other case alone.
Never touches a real submission -- it only ever writes the one fixed id below.
"""
from __future__ import annotations

import os
import shutil
import sys

from test_fixtures import demo_case

#: A fixed, obviously-synthetic id, so re-seeding replaces the demo rather than
#: piling up copies -- and so it can never collide with a real case's uuid.
DEMO_CASE_ID = "demo0000000000000000000000000000"


def main(data_dir: str = "data") -> int:
    target = os.path.join(data_dir, "cases", DEMO_CASE_ID)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)
    demo_case.build(target, case_id=DEMO_CASE_ID)
    print(f"seeded demo case at {target}")
    print("restart the API if it is running -- it caches its case list at startup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
```

`build` needs a `case_id` keyword for this. Add it, defaulting to the demo id.

- [ ] **Step 2: Verify end to end, by eye**

```bash
cd server && python3 seed_demo_case.py
python3 -m uvicorn app:app --host 127.0.0.1 --port 8002
```

In another terminal, `node_modules/.bin/vite --host 127.0.0.1 --port 5175 --strictPort`, then open
<http://127.0.0.1:5175>. **You must actually look at it.** Confirm: the demo case is in the list;
opening it shows three packets; opening a packet shows 25 tiêu chí with a mix of ✓, ✗, ! and ?; the
documents open and the pages render; the card images display.

Report what you saw. If a screen is blank, that is the finding — the manifest shape is wrong
somewhere, and it is much better found now than by the next person.

- [ ] **Step 3: Commit**

```bash
git add server/seed_demo_case.py server/test_fixtures/demo_case.py
git commit -m "feat(demo): one command seeds a synthetic case to browse"
```

---

## When you are done

Say plainly:

- what you actually saw on screen, screen by screen
- whether any manifest key had to differ from what you expected after reading `cases.py`
- which font `_font` ended up using on your machine
- your real test numbers, and the baseline you compared against
- anything you chose not to do, and why
