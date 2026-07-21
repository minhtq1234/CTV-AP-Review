# Stage A — OCR / extract → manifest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** From the source PDF + a packet's page range + its roster row, produce a `CtvFolder` manifest (matching `src/ctv/types.ts`) whose fields carry `expected` (roster) and `sources` (OCR value + bbox + confidence), so the existing reviewer validates it field-by-field with the auto-focus loupe.

**Architecture:** Pure extraction logic (line grouping, anchored pattern search, bbox union, DPI scaling, roster→expected, field assembly) — fully unit-tested on synthetic OCR word lists, no PDF/Tesseract needed. A thin I/O layer (PyMuPDF render + pytesseract) is verified on real packets by opening the manifest in the app. See `docs/superpowers/specs/2026-07-13-upload-split-ocr-validate-design.md`.

**Tech Stack:** Python 3, PyMuPDF (fitz), pytesseract (Tesseract `vie`), Pillow. Plain-`assert` tests run with `python3` from `server/`.

---

## File Structure

- **Create `server/ocr_extract.py`** — the module. Sections:
  - *Pure (unit-tested):*
    - `Word` — dict `{text, x, y, w, h, conf}` (display-space px, conf 0..1).
    - `scale_words(words_ocr, factor) -> list[Word]` — scale OCR-px boxes to display-px.
    - `group_lines(words, y_tol=8) -> list[list[Word]]` — cluster words into reading lines by y, each line x-sorted.
    - `union_bbox(words) -> {x,y,width,height}` — enclosing box of a word set.
    - `norm(s) -> str` — casefold + strip Vietnamese diacritics, for accent-insensitive anchor matching.
    - `find_in_lines(lines, anchors, pattern, allow_next_line=True) -> list[{value,bbox,confidence}]` — for each line whose text (accent-insensitively) contains any anchor, search that line (and optionally the next) for `pattern` over the joined word text; return the match value, union bbox of the words spanning the match, and min word confidence.
    - `FIELD_SPECS` — list of `{key,label,group,kind,anchors,pattern,roster_key}` for the 6 fields.
    - `PATTERNS` — `CCCD_SPACED`, `MST`, `MONEY`, `DATE`, `NAME` regexes (digits-with-optional-gaps for boxed forms).
    - `extract_fields(words_by_doc, roster_row) -> list[CtvField dict]` — run every spec over every doc/page's lines; assemble `sources` (one per doc/page hit); `expected` from `roster_row[roster_key]`; empty-source fallback so a missing value reads as an exception.
    - `build_manifest(folder_id, name, product, docs, fields) -> dict` — the `CtvFolder` dict.
  - *I/O (run-and-observe):*
    - `render_pages(pdf_path, start, end, out_dir, display_dpi=150) -> list[DocPage dict]` — render each page PNG, return `{src, width, height}` (src = written path/URL).
    - `ocr_words(pdf_path, page_index, ocr_dpi=300) -> (list[Word], factor)` — pytesseract `image_to_data` lang=`vie`; return OCR-space words + `display_dpi/ocr_dpi` scale factor.
    - `ocr_packet(pdf_path, start, end, roster_row, out_dir, name, product) -> dict` — orchestrate: render display pages, OCR each, scale, extract, assemble manifest; write `manifest.json`; return it.
- **Create `server/ocr_extract_test.py`** — plain-assert tests; `__main__` prints `ALL OK`.
- **Modify `server/README.md`** (create) — how to run the offline extract + PII note.

**Manifest field shape (must match `src/ctv/types.ts`):**
`CtvField` = `{key,label,group,check:"compare",kind,expected,sources:[{docId,page,value,bbox:{x,y,width,height},confidence}]}`; `CtvFolder` = `{id,name,product,heading:"Hồ sơ CTV",status:"pending",exempt:false,docs:[{id,kind,label,pages:[{src,width,height}]}],fields}`.

**PII:** the module takes all real paths as args; page PNGs + manifests write only to a caller-provided out_dir (scratchpad). Never commit output. Code only.

---

## Task A1: Pure geometry — scale, group_lines, union_bbox, norm

**Files:** Create `server/ocr_extract.py`, `server/ocr_extract_test.py`

- [ ] **Step 1: Failing test** — create `server/ocr_extract_test.py`:

```python
from ocr_extract import scale_words, group_lines, union_bbox, norm

def W(text, x, y, w, h, conf=90): return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}

def test_scale_words_halves_boxes():
    out = scale_words([W("a", 100, 200, 40, 20)], 0.5)
    assert out[0]["x"] == 50 and out[0]["y"] == 100 and out[0]["w"] == 20 and out[0]["h"] == 10
    assert out[0]["text"] == "a"

def test_group_lines_clusters_by_y():
    words = [W("Ho", 10, 100, 20, 18), W("ten", 40, 102, 20, 18), W("MST", 10, 200, 30, 18)]
    lines = group_lines(words, y_tol=8)
    assert len(lines) == 2
    assert [w["text"] for w in lines[0]] == ["Ho", "ten"]   # x-sorted, same row
    assert [w["text"] for w in lines[1]] == ["MST"]

def test_union_bbox_encloses():
    b = union_bbox([W("a", 10, 20, 30, 10), W("b", 50, 25, 20, 15)])
    assert b == {"x": 10, "y": 20, "width": 60, "height": 20}

def test_norm_strips_diacritics_and_case():
    assert norm("Mã số thuế") == "ma so thue"
    assert norm("CĂN CƯỚC") == "can cuoc"

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
```

- [ ] **Step 2: Run, expect fail** — `cd server && python3 ocr_extract_test.py` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement** the four pure helpers in `server/ocr_extract.py`. `norm` uses `unicodedata.normalize("NFD", s)` then drop combining marks + special-case `đ→d`; `group_lines` sorts by y, greedily starts a new line when a word's y-center exceeds the current line's baseline by `y_tol`, sorts each line by x; `union_bbox` = min x/y, max right/bottom; `scale_words` multiplies x/y/w/h by factor (round to int), keeps text/conf.

- [ ] **Step 4: Run, expect PASS.** — `ALL OK`.

- [ ] **Step 5: Commit** — `git add server/ocr_extract.py server/ocr_extract_test.py && git commit -m "feat(ocr): pure geometry helpers — scale, lines, bbox, norm"`

---

## Task A2: Anchored pattern search — `find_in_lines`

**Files:** Modify both files.

- [ ] **Step 1: Failing test** — add:

```python
from ocr_extract import find_in_lines, PATTERNS

def test_find_mst_on_anchor_line():
    lines = [[W("Mã", 10, 50, 20, 18), W("số", 35, 50, 15, 18), W("thuế", 55, 50, 25, 18),
              W("0303490096", 120, 50, 90, 18, conf=95)]]
    hits = find_in_lines(lines, anchors=["ma so thue"], pattern=PATTERNS["MST"])
    assert len(hits) == 1
    assert hits[0]["value"] == "0303490096"
    assert abs(hits[0]["confidence"] - 0.95) < 1e-6
    assert hits[0]["bbox"]["x"] == 120 and hits[0]["bbox"]["width"] == 90

def test_find_cccd_spaced_boxes_joins_digits():
    # boxed CCCD: single-digit words across the line
    digs = [W(d, 100 + i*20, 80, 12, 18) for i, d in enumerate("048091001309")]
    lines = [[W("Mã", 10, 80, 20, 18), W("số", 35, 80, 15, 18), W("thuế", 55, 80, 25, 18)] + digs]
    hits = find_in_lines(lines, anchors=["ma so thue"], pattern=PATTERNS["CCCD_SPACED"])
    assert hits and hits[0]["value"] == "048091001309"
    # bbox spans the 12 digit words
    assert hits[0]["bbox"]["x"] == 100 and hits[0]["bbox"]["width"] == 12*20 - 8

def test_find_value_on_next_line():
    lines = [[W("Ngày", 10, 50, 30, 18), W("sinh", 45, 50, 25, 18)],
             [W("24/04/1991", 10, 72, 90, 18, conf=88)]]
    hits = find_in_lines(lines, anchors=["ngay sinh"], pattern=PATTERNS["DATE"], allow_next_line=True)
    assert hits and hits[0]["value"] == "24/04/1991"

def test_find_returns_empty_when_no_anchor():
    lines = [[W("random", 10, 50, 40, 18)]]
    assert find_in_lines(lines, anchors=["ma so thue"], pattern=PATTERNS["MST"]) == []
```

- [ ] **Step 2: Run, expect fail** (ImportError on `find_in_lines`/`PATTERNS`).

- [ ] **Step 3: Implement** `PATTERNS` and `find_in_lines`:
  - `PATTERNS`: `MST = r"\d{10,13}"`; `CCCD_SPACED = r"\d(?:\s*\d){8,12}"` (match over joined line text, then strip spaces → the value); `MONEY = r"\d{1,3}(?:[.,]\d{3})+"`; `DATE = r"\d{1,2}/\d{1,2}/\d{4}"`; `NAME` handled specially (take the words after the anchor on the line).
  - `find_in_lines`: for each line, build `text = " ".join(w["text"] ...)`; if any `anchor in norm(text)`: run `re.search(pattern, text)` on that line (and the next if `allow_next_line` and no hit); map the matched character span back to the contributing words (walk words accumulating lengths) → `bbox = union_bbox(matched_words)`, `confidence = min(conf)/100`, `value = matched.replace(" ", "")` for digit patterns. Return all hits.
  - Provide a `NAME` path: `find_name(lines, anchors)` returns the words to the right of the anchor on its line (or the next line), value = their joined text, bbox = union. (Add a matching test if you split it out.)

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** — `feat(ocr): anchored pattern search with bbox + spaced-digit support`

---

## Task A3: Field assembly — `extract_fields`, `FIELD_SPECS`, `build_manifest`

**Files:** Modify both files.

- [ ] **Step 1: Failing test** — add a test that feeds a small `words_by_doc` (2 docs, a few lines each incl. an MST line and a name line) + a `roster_row` dict, then asserts:
  - one `CtvField` per spec; `check == "compare"`; `expected` equals the roster value;
  - a field found in both docs has 2 `sources` (each with `docId`, `page`, `value`, `bbox`, `confidence`);
  - a field with no OCR hit still appears, with a single empty/low-confidence source (so it renders as an exception);
  - `build_manifest(...)` returns a dict with `id,name,product,heading,status:"pending",exempt:false,docs,fields` and every field/source key matching `src/ctv/types.ts`.

Write concrete inputs/expected values in the test (no placeholders).

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** `FIELD_SPECS` (6 entries: hoten/cccd/mst/tk/ngaysinh/phi with anchors + pattern + roster_key + group + kind — kinds: name/text/number/date per `FieldKind`), `extract_fields` (loop specs × docs × their `group_lines`; gather sources; expected from `roster_row.get(roster_key,"")`; empty-source fallback), and `build_manifest`.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** — `feat(ocr): field assembly into CtvFolder manifest (expected=roster, sources=OCR)`

---

## Task A4: I/O layer — render, OCR, orchestrate `ocr_packet`

**Files:** Modify `server/ocr_extract.py`. No unit test (PDF/Tesseract I/O); verified in A5.

- [ ] **Step 1: Implement**
  - `render_pages(pdf_path, start, end, out_dir, display_dpi=150)`: for each page in `[start,end]`, render PNG to `out_dir` (name `pg{n}.png`), return `DocPage` dicts `{src, width, height}` (src = absolute path for offline; the server will later rewrite to a URL). Group the packet's pages into `docs` — for Stage A keep it simple: one `EvidenceDoc` `{id:"packet", kind:"contract", label:"Hồ sơ", pages:[...]}` holding all pages (doc-type segmentation is a later refinement).
  - `ocr_words(pdf_path, page_index, ocr_dpi=300)`: render the page at `ocr_dpi`, `pytesseract.image_to_data(img, lang="vie", output_type=DICT)`; build `Word` dicts (skip empty text / conf<0); return `(words, display_dpi/ocr_dpi)`.
  - `ocr_packet(pdf_path, start, end, roster_row, out_dir, name, product)`: render display pages; for each page OCR→scale→`group_lines`; build `words_by_doc = {"packet": {page_index: scaled_words}}` (page index relative to packet start); `fields = extract_fields(...)`; `docs` from `render_pages`; `manifest = build_manifest(...)`; write `manifest.json` into `out_dir`; return it. Source `docId="packet"`, `page` = relative page index.

- [ ] **Step 2: Import check** — `cd server && python3 -c "import ocr_extract; print('ok')"` → `ok`.

- [ ] **Step 3: Commit** — `feat(ocr): I/O layer — render pages, tesseract vie, ocr_packet orchestration`

---

## Task A5: End-to-end verification on real packets (offline)

**Files:** none (verification). Uses the real PDF + roster + scratchpad.

- [ ] **Step 1: Write a throwaway driver** in the scratchpad (NOT committed) that:
  - reads the roster via the splitter's `_roster_rows` + `extract_roster_names`, and builds a `roster_row` dict for a chosen packet by mapping roster columns → the 6 field keys (name, CCCD, MST, TK, ngày sinh, phí);
  - calls `ocr_packet` for 2–3 real packets — include the amber **Trần Ứng Hỷ (p193–200)** — writing manifests + page PNGs under `$SCRATCH/ocr/<packet>/`.

- [ ] **Step 2: Run it.** Confirm each manifest has 6 fields, most with ≥1 source, and that typed fields (MST/CCCD/bank on the biên-bản/tax-lookup pages) carry the correct value matching the roster (compare programmatically; print match/no-match, not raw PII).

- [ ] **Step 3: Verify in the app.** Temporarily point the app's manifest loader at one real manifest (served over http from the scratchpad `ocr/` dir with page PNGs alongside; or copy into `public/` under a gitignored path) and open it in `FolderReview`. Confirm: fields render; typed fields show green matches; the loupe auto-focuses the correct spot on the real scan; handwritten fields read as low-conf/mismatch. Capture a screenshot. Revert any temporary wiring.

- [ ] **Step 4: Report** the per-packet field hit-rate (how many of 6 fields got a source; how many typed matched the roster) and any bbox-alignment issues. Do NOT commit manifests/PNGs (PII).

---

## Self-Review Notes

- **Spec coverage:** render+scale (A1/A4), OCR+bboxes (A4), anchored extraction incl. spaced boxes (A2), expected=roster + sources + missing→exception (A3), manifest matches `types.ts` (A3), e2e loupe alignment on real data (A5). PII: out_dir-only, code-only commits (all tasks).
- **Type consistency:** `Word` keys `{text,x,y,w,h,conf}`; bbox `{x,y,width,height}`; source `{docId,page,value,bbox,confidence}`; field `{key,label,group,check,kind,expected,sources}` — used identically across A1–A4 and match `src/ctv/types.ts`.
- **Placeholder scan:** function contracts + concrete test cases given; A-tasks TDD the pure logic. (This plan pins the tricky pure logic with code/tests and leaves mechanical assembly to TDD against explicit contracts — appropriate for a fiddly OCR module.)
