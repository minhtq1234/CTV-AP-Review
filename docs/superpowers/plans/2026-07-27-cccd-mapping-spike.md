# CCCD Mapping Go/No-Go Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a local-only spike that measures whether embedded CCCD images can be extracted, paired, region-read, and matched exactly to the roster with enough accuracy to justify the production feature.

**Architecture:** Five isolated Python units handle OOXML extraction, local OCR/number-region location, conservative side pairing, duplicate-aware roster resolution, and aggregate spike reporting. Nothing is wired into `pipeline.py`, `CaseStore`, the API, manifests, checklists, or React during this plan. A manually audited ground-truth file drives zero-false-match validation and the final proceed/revise/stop decision.

**Tech Stack:** Python 3, standard-library `zipfile`/`xml.etree.ElementTree`/`dataclasses`, Pillow, pytesseract, pytest, the existing roster reader in `detect_packets`, and existing Vietnamese normalization in `ocr_extract`.

## Global Constraints

- Target the clean `main` checklist architecture at commit `3ed4b29` or later.
- Phase 0 only: no edits to `server/pipeline.py`, `server/app.py`, `server/cases.py`, `server/checklist.py`, `src/`, manifests, case data, or production routes.
- Process CCCD images and OCR entirely locally; never call GreenNode or another external service.
- Never commit the supplied workbook, corresponding roster, ground truth, extracted images, contact sheets, OCR output, or real spike report.
- Automatic spike placement requires a located number region, exactly 12 digits, confidence `>= 0.85`, and exactly one roster row.
- Fuzzy digits, edit distance, 9-digit CMND, name-only, no-region, low-confidence, duplicate, and conflicting results are never automatic.
- Pair only opposite known sides on the same sheet when row overlap is `>= 50%` or start-row distance is `<= 1`, using mutual nearest neighbors with a `>= 20%` margin over alternatives.
- Limits: workbook `<= 100 MB`; `<= 500` drawing instances; each embedded image `<= 25 MB`; accepted uncompressed images `<= 500 MB` total; each decoded image `<= 40` megapixels.
- Synthetic PII-free fixtures only in committed tests.
- Spike thresholds: 100% supported drawing extraction; zero false pairs; zero false exact roster matches; exact coverage `>= 85%`; exact plus unique-name suggestion coverage `>= 95%`; manual-search rate `<= 5%`.
- Placement denominator: unique roster rows whose normalized CCCD is exactly 12 digits.
- One tuning iteration is allowed. Failed iteration 1 returns `revise`; failed iteration 2 returns `stop`.

---

## File Structure

- Create `server/cccd_workbook.py` — safe OOXML drawing extraction and image validation.
- Create `server/cccd_workbook_test.py` — synthetic multi-sheet workbook and archive-security tests.
- Create `server/cccd_ocr.py` — image orientation, side classification, number-region location, region-only digit OCR, and name extraction.
- Create `server/cccd_ocr_test.py` — pure word/geometry tests plus mocked pytesseract adapter tests.
- Create `server/cccd_pairing.py` — deterministic conservative front/back pairing.
- Create `server/cccd_pairing_test.py` — valid, incomplete, competing, and ambiguous pairing tests.
- Create `server/cccd_matching.py` — duplicate-aware roster indexes and exact/suggested/manual resolution.
- Create `server/cccd_matching_test.py` — exact-only safety and duplicate/conflict tests.
- Create `server/cccd_spike.py` — orchestration, ground-truth audit, metric calculation, threshold decision, and CLI.
- Create `server/cccd_spike_test.py` — aggregate metrics, masking, and proceed/revise/stop tests.
- Create `docs/cccd-spike-runbook.md` — local input contract, ground-truth schema, commands, and PII handling.

---

### Task 1: Safe OOXML Drawing Extraction

**Files:**
- Create: `server/cccd_workbook.py`
- Create: `server/cccd_workbook_test.py`

**Interfaces:**
- Consumes: `.xlsx` filesystem path and caller-owned output directory.
- Produces:

```python
@dataclass(frozen=True)
class Anchor:
    sheet: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int

@dataclass(frozen=True)
class EmbeddedDrawing:
    id: str
    anchor: Anchor
    media_type: str
    extension: str
    width: int
    height: int
    sha256: str
    stored_path: str

@dataclass(frozen=True)
class ExtractionIssue:
    code: str
    drawing_id: str | None

@dataclass(frozen=True)
class ExtractionResult:
    drawing_instances: int
    drawings: list[EmbeddedDrawing]
    issues: list[ExtractionIssue]

def extract_drawings(xlsx_path: str, output_dir: str) -> ExtractionResult:
    ...
```

- Limits exported as `MAX_WORKBOOK_BYTES`, `MAX_DRAWINGS`, `MAX_IMAGE_BYTES`, `MAX_TOTAL_IMAGE_BYTES`, and `MAX_PIXELS`.

- [ ] **Step 1: Write failing extraction-order and multi-sheet tests**

Build a minimal synthetic OOXML archive in the test using `zipfile.ZipFile`.
Deliberately map worksheet anchors to media filenames in non-lexical order.

```python
def test_extract_drawings_follows_relationships_not_media_names(tmp_path):
    book = tmp_path / "cards.xlsx"
    _write_synthetic_xlsx(
        book,
        sheets=[
            ("Cards A", [
                ("rId9", "xl/media/image20.png", (1, 0, 10, 1), _png("front-a")),
                ("rId2", "xl/media/image3.png", (1, 1, 10, 2), _png("back-a")),
            ]),
            ("Cards B", [
                ("rId4", "xl/media/image1.jpeg", (20, 0, 28, 1), _jpeg("front-b")),
            ]),
        ],
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert result.drawing_instances == 3
    assert [(d.anchor.sheet, d.anchor.from_row, d.extension) for d in result.drawings] == [
        ("Cards A", 1, "png"),
        ("Cards A", 1, "png"),
        ("Cards B", 20, "jpg"),
    ]
    assert all(os.path.isfile(d.stored_path) for d in result.drawings)
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
python -m pytest -q server/cccd_workbook_test.py::test_extract_drawings_follows_relationships_not_media_names
```

Expected: collection fails because `cccd_workbook` does not exist.

- [ ] **Step 3: Implement relationship traversal and validated extraction**

Use only public OOXML parts and standard-library XML:

```python
def extract_drawings(xlsx_path: str, output_dir: str) -> ExtractionResult:
    if os.path.getsize(xlsx_path) > MAX_WORKBOOK_BYTES:
        raise CccdWorkbookError("workbook-too-large")
    with zipfile.ZipFile(xlsx_path) as archive:
        _reject_encrypted_entries(archive)
        sheet_parts = _worksheet_parts_in_workbook_order(archive)
        records = []
        for sheet_name, sheet_part in sheet_parts:
            for drawing_part in _drawing_parts_for_sheet(archive, sheet_part):
                records.extend(
                    _drawing_records(archive, sheet_name, drawing_part)
                )
        return _decode_and_store(archive, records, output_dir)
```

Resolve worksheet, drawing, and media targets with a helper that normalizes
POSIX OOXML paths and rejects any target that escapes the archive root.
Generate stored names from drawing IDs, never archive filenames.

- [ ] **Step 4: Add failing validation tests**

Cover:

```python
@pytest.mark.parametrize("fixture, code", [
    ("external-image-rel", "external-relationship"),
    ("path-traversal-rel", "invalid-target"),
    ("unsupported-gif", "unsupported-media"),
    ("malformed-drawing", "malformed-drawing"),
])
def test_invalid_drawing_is_reported_without_path_access(tmp_path, fixture, code):
    book = _malicious_or_invalid_xlsx(tmp_path, fixture)
    result = extract_drawings(str(book), str(tmp_path / "out"))
    assert any(issue.code == code for issue in result.issues)
    assert not any(".." in d.stored_path for d in result.drawings)
```

Add hard-failure tests for workbook, drawing-count, per-image, total-image, and
pixel limits. Monkeypatch constants downward so fixtures remain tiny.

- [ ] **Step 5: Run the full extractor test file**

Run:

```bash
python -m pytest -q server/cccd_workbook_test.py
```

Expected: all extraction, ordering, and safety tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/cccd_workbook.py server/cccd_workbook_test.py
git commit -m "feat(spike): extract embedded CCCD drawings safely"
```

---

### Task 2: Side Classification and Region-Located OCR

**Files:**
- Create: `server/cccd_ocr.py`
- Create: `server/cccd_ocr_test.py`

**Interfaces:**
- Consumes: `EmbeddedDrawing.stored_path`.
- Produces:

```python
Side = Literal["front", "back", "unknown"]

@dataclass(frozen=True)
class OcrWord:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

@dataclass(frozen=True)
class CccdImageOcr:
    side: Side
    side_confidence: float
    cccd: str
    cccd_confidence: float
    name: str
    name_confidence: float
    number_bbox: dict[str, int] | None

def classify_side(words: list[OcrWord]) -> tuple[Side, float]:
    ...

def locate_number_region(
    words: list[OcrWord],
    image_width: int,
    image_height: int,
) -> dict[str, int] | None:
    ...

def analyze_drawing(drawing: EmbeddedDrawing) -> CccdImageOcr:
    ...
```

- [ ] **Step 1: Write failing pure side and region tests**

```python
def test_front_markers_classify_front_and_locate_adjacent_number():
    words = [
        OcrWord("CĂN", 20, 10, 40, 15, .98),
        OcrWord("CƯỚC", 65, 10, 50, 15, .98),
        OcrWord("CÔNG", 120, 10, 45, 15, .98),
        OcrWord("DÂN", 170, 10, 35, 15, .98),
        OcrWord("Số:", 20, 80, 30, 18, .96),
        OcrWord("079123456789", 60, 80, 150, 18, .94),
        OcrWord("Họ", 20, 130, 20, 18, .95),
        OcrWord("và", 45, 130, 20, 18, .95),
        OcrWord("tên:", 70, 130, 35, 18, .95),
    ]
    side, confidence = classify_side(words)
    bbox = locate_number_region(words, 400, 250)
    assert side == "front"
    assert confidence >= .9
    assert bbox == {"x": 54, "y": 74, "width": 162, "height": 30}

def test_digits_elsewhere_without_number_label_produce_no_region():
    words = [OcrWord("01/02/2026", 20, 100, 100, 18, .99)]
    assert locate_number_region(words, 400, 250) is None
```

Include back markers and an unknown image test.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest -q server/cccd_ocr_test.py -k "classify or region"
```

Expected: collection fails because `cccd_ocr` does not exist.

- [ ] **Step 3: Implement pure marker and geometry logic**

Reuse `ocr_extract.norm` for Vietnamese normalization. Recognize front marker
groups (`căn cước công dân`, number label, name label, birth-date label) and
back marker groups (identification features, issue date, authority). Return
`unknown` when neither side reaches two independent marker groups.

For the number box:

```python
def locate_number_region(words, image_width, image_height):
    lines = _group_words_into_lines(words)
    for line_index, line in enumerate(lines):
        label = _number_label_span(line)
        if label:
            same_line = _words_right_of(line, label, min_confidence=.5)
            target = same_line or _next_line_digits(lines, line_index)
            if target:
                return _padded_union(target, image_width, image_height, pad=6)
    return None
```

Do not scan for arbitrary digit runs outside this region.

- [ ] **Step 4: Write failing adapter test proving OCR is region-only**

Monkeypatch private adapters rather than invoking Tesseract:

```python
def test_analyze_drawing_reads_digits_only_from_located_crop(tmp_path, monkeypatch):
    drawing = _drawing(tmp_path, width=400, height=250)
    monkeypatch.setattr(co, "_upright_image", lambda path: Image.new("RGB", (400, 250)))
    monkeypatch.setattr(co, "_full_image_words", lambda image: FRONT_WORDS)
    seen = {}
    def fake_digits(image, bbox):
        seen["bbox"] = bbox
        return "079123456789", .93
    monkeypatch.setattr(co, "_region_digits", fake_digits)
    monkeypatch.setattr(co, "_name_from_words", lambda words: ("Nguyen Van A", .91))

    result = analyze_drawing(drawing)

    assert result.cccd == "079123456789"
    assert result.cccd_confidence == .93
    assert seen["bbox"] == result.number_bbox
```

Add a test that `_region_digits` is never called when the label/box is absent.

- [ ] **Step 5: Implement the local Tesseract adapter**

- Load with Pillow and apply EXIF transpose.
- Call `pytesseract.image_to_osd`; reuse `ocr_extract._upright_rotation` for
  angle math, but do not call PDF-specific `detect_page_rotation`.
- Run one full-image `image_to_data` pass for words/geometry.
- Crop only `number_bbox`.
- Run the crop with `--psm 7 -c tessedit_char_whitelist=0123456789`.
- Normalize output to digits.
- Accept a CCCD value only when it is exactly 12 digits; retain shorter/longer
  text as empty for automatic matching.
- Extract the name from labeled full-image words for suggestions.

- [ ] **Step 6: Run OCR tests and Tesseract preflight**

Run:

```bash
python -m pytest -q server/cccd_ocr_test.py
python -c "import pytesseract; print(pytesseract.get_tesseract_version())"
```

Expected: all tests pass and Tesseract prints a version without error.

- [ ] **Step 7: Commit**

```bash
git add server/cccd_ocr.py server/cccd_ocr_test.py
git commit -m "feat(spike): locate and read CCCD number regions"
```

---

### Task 3: Conservative Front/Back Pairing

**Files:**
- Create: `server/cccd_pairing.py`
- Create: `server/cccd_pairing_test.py`

**Interfaces:**
- Consumes: `EmbeddedDrawing` plus `CccdImageOcr`.
- Produces:

```python
@dataclass(frozen=True)
class AnalyzedDrawing:
    drawing: EmbeddedDrawing
    ocr: CccdImageOcr

@dataclass(frozen=True)
class CardCandidate:
    id: str
    front: AnalyzedDrawing | None
    back: AnalyzedDrawing | None
    issues: tuple[str, ...]

def pair_drawings(images: list[AnalyzedDrawing]) -> list[CardCandidate]:
    ...
```

- [ ] **Step 1: Write failing pairing tests**

```python
def test_pairs_mutual_nearest_opposite_sides_with_margin():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    back = analyzed("b1", "back", anchor=(1, 1, 10, 2))
    far_back = analyzed("b2", "back", anchor=(30, 1, 39, 2))
    out = pair_drawings([far_back, back, front])
    paired = next(c for c in out if c.front and c.front.drawing.id == "f1")
    assert paired.back.drawing.id == "b1"

def test_ambiguous_neighbor_is_not_paired():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    b1 = analyzed("b1", "back", anchor=(1, 1, 10, 2))
    b2 = analyzed("b2", "back", anchor=(2, 1, 11, 2))
    out = pair_drawings([front, b1, b2])
    candidate = next(c for c in out if c.front)
    assert candidate.back is None
    assert "ambiguous-pair" in candidate.issues
```

Also test same-side images, other sheets, insufficient row overlap, front-only,
back-only, unknown-side, stable input-independent output order, and no image
assigned twice.

- [ ] **Step 2: Run and verify failure**

Run:

```bash
python -m pytest -q server/cccd_pairing_test.py
```

Expected: collection fails because `cccd_pairing` does not exist.

- [ ] **Step 3: Implement eligibility, distance, and mutual-nearest selection**

```python
def _eligible(front, back):
    if front.drawing.anchor.sheet != back.drawing.anchor.sheet:
        return False
    overlap = _vertical_overlap_ratio(front.drawing.anchor, back.drawing.anchor)
    row_delta = abs(front.drawing.anchor.from_row - back.drawing.anchor.from_row)
    return overlap >= .5 or row_delta <= 1

def _has_margin(best, alternatives):
    if not alternatives:
        return True
    return best <= min(alternatives) * .8
```

Accept a pair only if each is the other's nearest eligible opposite side and
both margins pass. Generate candidate IDs from stable drawing IDs, not list
positions.

- [ ] **Step 4: Run pairing tests**

Run:

```bash
python -m pytest -q server/cccd_pairing_test.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/cccd_pairing.py server/cccd_pairing_test.py
git commit -m "feat(spike): pair CCCD sides conservatively"
```

---

### Task 4: Exact-Only Roster Resolution

**Files:**
- Create: `server/cccd_matching.py`
- Create: `server/cccd_matching_test.py`

**Interfaces:**
- Consumes: `CardCandidate[]` and roster rows returned by
  `pipeline.all_roster_rows`.
- Produces:

```python
ResolutionState = Literal["exact", "suggested", "manual", "conflict"]

@dataclass(frozen=True)
class CardResolution:
    candidate_id: str
    state: ResolutionState
    roster_key: str | None
    matched_by: Literal["cccd", "name"] | None
    issues: tuple[str, ...]

@dataclass(frozen=True)
class ResolutionResult:
    expected_mappable_identities: int
    resolutions: list[CardResolution]

def resolve_candidates(
    candidates: list[CardCandidate],
    roster_rows: list[dict[str, str]],
) -> ResolutionResult:
    ...
```

`roster_key` is an opaque spike-only ID generated from roster row order. It is
not a name or CCCD and is safe for aggregate evaluation.

- [ ] **Step 1: Write failing exact/suggestion/manual tests**

```python
def test_high_confidence_exact_12_digit_unique_match_is_exact():
    card = candidate("c1", cccd="079123456789", cccd_conf=.92, name="A", name_conf=.9)
    rows = [{"name": "A", "cccd": "079123456789"}]
    result = resolve_candidates([card], rows)
    assert result.expected_mappable_identities == 1
    assert result.resolutions[0].state == "exact"
    assert result.resolutions[0].matched_by == "cccd"

@pytest.mark.parametrize("cccd, confidence", [
    ("079123456788", .99),  # fuzzy by one digit: still manual
    ("123456789", .99),     # CMND: manual
    ("079123456789", .84),  # below threshold: manual/suggested
])
def test_non_exact_or_low_confidence_never_auto_matches(cccd, confidence):
    card = candidate("c1", cccd=cccd, cccd_conf=confidence, name="", name_conf=0)
    rows = [{"name": "A", "cccd": "079123456789"}]
    assert resolve_candidates([card], rows).resolutions[0].state != "exact"
```

Add unique name suggestion, duplicate name, duplicate CCCD, conflicting
CCCD/name, no front, no region, duplicate candidate target, and unreadable
tests.

- [ ] **Step 2: Run and verify failure**

Run:

```bash
python -m pytest -q server/cccd_matching_test.py
```

Expected: collection fails because `cccd_matching` does not exist.

- [ ] **Step 3: Implement duplicate-aware indexes and resolution precedence**

```python
def _index_many(rows, key_fn):
    out = {}
    for index, row in enumerate(rows):
        key = key_fn(row)
        if key:
            out.setdefault(key, []).append((index, row))
    return out

def resolve_candidates(candidates, roster_rows):
    by_cccd = _index_many(roster_rows, lambda row: _digits(row.get("cccd", "")))
    by_name = _index_many(roster_rows, lambda row: norm(row.get("name", "")))
    # exact 12 digits + confidence + unique target first
    # unique name creates state="suggested", never state="exact"
    # all other paths remain manual/conflict
```

Count `expected_mappable_identities` from unique normalized 12-digit roster
CCCD keys, including identities with no extracted candidate.

Use that same fixed denominator for all placement metrics:

- `exact_rate = exact_matches / expected_mappable_identities`;
- `assisted_rate = (exact_matches + unique_name_suggestions) /
  expected_mappable_identities`; and
- `manual_search = expected_mappable_identities - exact_matches -
  unique_name_suggestions`, with
  `manual_search_rate = manual_search / expected_mappable_identities`.

Treat zero expected identities as invalid input rather than reporting a passing
rate.

- [ ] **Step 4: Run matching tests**

Run:

```bash
python -m pytest -q server/cccd_matching_test.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/cccd_matching.py server/cccd_matching_test.py
git commit -m "feat(spike): resolve CCCD cards with exact-only matching"
```

---

### Task 5: Audited Metrics and Go/No-Go CLI

**Files:**
- Create: `server/cccd_spike.py`
- Create: `server/cccd_spike_test.py`
- Create: `docs/cccd-spike-runbook.md`

**Interfaces:**
- Consumes: CCCD workbook, roster workbook, private ground-truth JSON, output
  directory, and iteration number.
- Produces: aggregate `SpikeReport`; writes one PII-free aggregate JSON report.

```python
@dataclass(frozen=True)
class SpikeMetrics:
    expected_mappable_identities: int
    supported_drawing_instances: int
    extracted_drawings: int
    proposed_pairs: int
    false_pairs: int
    exact_matches: int
    false_exact_matches: int
    unique_name_suggestions: int
    manual_search: int
    extraction_rate: float
    exact_rate: float
    assisted_rate: float
    manual_search_rate: float

@dataclass(frozen=True)
class SpikeReport:
    iteration: int
    decision: Literal["proceed", "revise", "stop"]
    metrics: SpikeMetrics
    thresholds: dict[str, float | int]

def run_spike(
    workbook_path: str,
    roster_path: str,
    ground_truth_path: str,
    output_dir: str,
    iteration: int,
) -> SpikeReport:
    ...
```

- [ ] **Step 1: Write failing threshold-decision tests**

```python
def test_passing_metrics_proceed():
    metrics = metric_fixture(
        extraction_rate=1.0,
        false_pairs=0,
        false_exact_matches=0,
        exact_rate=.87,
        assisted_rate=.97,
        manual_search_rate=.03,
    )
    assert decide(metrics, iteration=1) == "proceed"

def test_first_failed_safe_run_requests_one_revision():
    metrics = metric_fixture(
        extraction_rate=1.0,
        false_pairs=0,
        false_exact_matches=0,
        exact_rate=.80,
        assisted_rate=.96,
        manual_search_rate=.04,
    )
    assert decide(metrics, iteration=1) == "revise"
    assert decide(metrics, iteration=2) == "stop"

def test_any_false_auto_match_stops_even_on_iteration_one():
    metrics = metric_fixture(false_exact_matches=1)
    assert decide(metrics, iteration=1) == "stop"
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
python -m pytest -q server/cccd_spike_test.py -k "proceed or revision or false"
```

Expected: collection fails because `cccd_spike` does not exist.

- [ ] **Step 3: Define and test the private ground-truth contract**

The runbook specifies a local untracked file:

```json
{
  "cards": [
    {
      "frontDrawingId": "drawing-001",
      "backDrawingId": "drawing-002",
      "rosterCccd": "000000000001"
    }
  ]
}
```

Use synthetic values only in the committed documentation. The real file must
live outside the repository.

Tests must reject duplicate drawing IDs, unknown drawing IDs, duplicate truth
CCCDs, non-12-digit truth values, and missing audit coverage.

- [ ] **Step 4: Implement orchestration and aggregate evaluation**

`run_spike`:

1. creates a temporary extraction directory under `output_dir`;
2. calls `extract_drawings`;
3. calls `analyze_drawing` for each extracted drawing;
4. calls `pair_drawings`;
5. reads the roster with `detect_packets._roster_rows` and converts it through
   `pipeline.all_roster_rows`;
6. calls `resolve_candidates`;
7. loads and validates ground truth;
8. compares proposed pairs and exact resolutions to truth;
9. computes rates with the fixed roster denominator;
10. applies threshold decision logic; and
11. writes only aggregate keys from `SpikeReport`.

The report must not include filenames, sheet names, anchors, drawing IDs,
names, CCCD values, candidate rows, or OCR text.

- [ ] **Step 5: Add a PII-leak regression test**

```python
def test_written_report_contains_only_aggregate_schema(tmp_path, monkeypatch):
    report = run_with_synthetic_fakes(tmp_path, monkeypatch)
    raw = (tmp_path / "report" / "cccd-spike-report.json").read_text()
    assert "Nguyen" not in raw
    assert "000000000001" not in raw
    assert "drawing-001" not in raw
    assert set(json.loads(raw)) == {"iteration", "decision", "metrics", "thresholds"}
```

- [ ] **Step 6: Implement CLI and exit codes**

```bash
python server/cccd_spike.py \
  --workbook "$CCCD_SPIKE_WORKBOOK" \
  --roster "$CCCD_SPIKE_ROSTER" \
  --ground-truth "$CCCD_SPIKE_GROUND_TRUTH" \
  --output-dir "$CCCD_SPIKE_OUTPUT" \
  --iteration 1
```

Exit codes:

- `0` — `proceed`
- `2` — `revise`
- `3` — `stop`
- `4` — invalid/missing private input or audit coverage

The CLI prints only the aggregate decision and metrics.

- [ ] **Step 7: Write the runbook**

Document:

- required environment variables;
- exact CLI command;
- private ground-truth schema;
- how to audit every proposed pair and exact match locally;
- iteration-1 and iteration-2 rules;
- report schema and exit codes;
- deletion of extraction/output directories after the decision; and
- prohibition on committing real inputs or results.

- [ ] **Step 8: Run CLI tests**

Run:

```bash
python -m pytest -q server/cccd_spike_test.py
```

Expected: all orchestration, validation, masking, and decision tests pass.

- [ ] **Step 9: Commit**

```bash
git add server/cccd_spike.py server/cccd_spike_test.py docs/cccd-spike-runbook.md
git commit -m "feat(spike): report CCCD mapping viability"
```

---

### Task 6: Full Verification and Real Go/No-Go Run

**Files:**
- Verify only; do not commit real outputs.

**Interfaces:**
- Consumes the completed spike CLI and private local inputs.
- Produces the user-facing aggregate decision and metrics only.

- [ ] **Step 1: Run focused spike tests**

```bash
python -m pytest -q \
  server/cccd_workbook_test.py \
  server/cccd_ocr_test.py \
  server/cccd_pairing_test.py \
  server/cccd_matching_test.py \
  server/cccd_spike_test.py
```

Expected: all pass.

- [ ] **Step 2: Run full backend regression**

```bash
python -m pytest -q server
```

Expected: all existing and spike backend tests pass.

- [ ] **Step 3: Run unchanged frontend verification**

```bash
npm test
npm run build
```

Expected: Vitest and production build pass.

- [ ] **Step 4: Confirm private inputs before the real run**

Set:

```bash
export CCCD_SPIKE_OUTPUT="/private/tmp/ctv-cccd-spike"
: "${CCCD_SPIKE_WORKBOOK:?Set CCCD_SPIKE_WORKBOOK to the user-provided CCCD workbook path}"
: "${CCCD_SPIKE_ROSTER:?Set CCCD_SPIKE_ROSTER to the user-provided corresponding roster path}"
: "${CCCD_SPIKE_GROUND_TRUTH:?Set CCCD_SPIKE_GROUND_TRUTH to the user-provided private audit JSON path}"
test -f "$CCCD_SPIKE_WORKBOOK"
test -f "$CCCD_SPIKE_ROSTER"
test -f "$CCCD_SPIKE_GROUND_TRUTH"
```

All three private input paths must be supplied by the user. Do not guess them
or substitute an unrelated workbook. Stop here if any input is unavailable.

- [ ] **Step 5: Run iteration 1**

```bash
python server/cccd_spike.py \
  --workbook "$CCCD_SPIKE_WORKBOOK" \
  --roster "$CCCD_SPIKE_ROSTER" \
  --ground-truth "$CCCD_SPIKE_GROUND_TRUTH" \
  --output-dir "$CCCD_SPIKE_OUTPUT" \
  --iteration 1
```

Expected: aggregate `proceed`, `revise`, or `stop`; no PII printed.

- [ ] **Step 6: Apply the decision**

- `proceed` — stop this plan and write a separate full-build implementation
  plan from the approved design.
- `revise` — make one focused change to number-region/OCR tuning, add a
  regression test for that change, rerun all focused tests, then rerun the CLI
  with `--iteration 2`.
- `stop` — do not implement persistence/API/checklist/frontend work; report
  which aggregate threshold failed and recommend a structured CCCD index.

- [ ] **Step 7: Remove private output**

After recording the aggregate result for the user:

```bash
python -c "import os, shutil; p=os.environ['CCCD_SPIKE_OUTPUT']; assert p.startswith('/private/tmp/ctv-cccd-spike'); shutil.rmtree(p, ignore_errors=True)"
```

Expected: the local extraction/report directory is removed. Never stage or
commit a real result.

---

## Self-Review Checklist

- Spec coverage: extraction, classification, pairing, region OCR, exact-only
  matching, name suggestions, duplicate detection, fixed denominator,
  thresholds, one tuning iteration, local PII handling, and stop gate all map
  to Tasks 1–6.
- Scope: no production pipeline/store/API/checklist/frontend code is modified.
- Type consistency: `EmbeddedDrawing` → `AnalyzedDrawing` → `CardCandidate` →
  `CardResolution` → `SpikeMetrics` names and fields are stable across tasks.
- Safety: whole-image digits, fuzzy matching, 9-digit CMND, low confidence,
  duplicate roster IDs, and ambiguous pairs cannot produce `state="exact"`.
- Privacy: committed tests use synthetic values; written real report is
  aggregate-only; private outputs are removed.
- Execution gate: Task 6 cannot run without the corresponding roster and
  reviewer ground truth; it explicitly forbids guessing either path.
