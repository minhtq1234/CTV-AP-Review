# CCCD Geometry and Accuracy Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CCCD image pairing conservative for both one-cell and two-cell OOXML anchors, and qualify every extractor version with reproducible safety and reviewer-efficiency metrics.

**Architecture:** Preserve the native anchor type, origin offsets, and declared image extents instead of inventing cell bounds. Pair two-cell anchors by their existing overlap logic and one-cell anchors by conservative same-sheet origin alignment, abstaining when geometry is insufficient. Add a private-safe evaluation contract and CLI that compares versioned predictions with anonymized reviewer-confirmed labels.

**Tech Stack:** Python 3, OOXML/ZIP/XML, Pillow, pytest, JSON, CSV.

**Spec:** `docs/superpowers/specs/2026-08-20-packet-boundary-safety-and-correction-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-25-identity-isolated-extraction.md`

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1` on branch `ver1`.
- Preserve and reconcile the existing uncommitted `server/cccd_workbook.py` and `server/cccd_workbook_test.py` edits; never overwrite or discard them.
- Keep the current archive, XML, image-count, image-size, pixel, and path-safety limits.
- Never commit real names, CCCD values, source workbooks, scans, OCR text, or local source paths.
- Automatic attachment requires an exact 12-digit CCCD, one unique roster/packet target, both sides, no side conflict, and successful evidence writes.
- Ambiguous or unsupported geometry produces review evidence, never a guessed pair.
- Every prediction and measurement records an extractor version.
- Release gates prioritize zero cross-person contamination and zero false-clear results over coverage.

---

### Task 1: Preserve native one-cell anchor extents

**Files:**
- Modify: `server/cccd_workbook.py:30-52,138-224`
- Modify: `server/cccd_workbook_test.py`

**Interfaces:**
- Consumes: OOXML `twoCellAnchor` with `<from>/<to>` and `oneCellAnchor` with `<from>/<ext cx cy>`.
- Produces: `Anchor.anchor_type`, `extent_cx`, `extent_cy`; no invented `to_row/to_col` for one-cell anchors.

- [ ] **Step 1: Inspect and preserve the dirty baseline**

Run:

```bash
git status --short -- server/cccd_workbook.py server/cccd_workbook_test.py
git diff -- server/cccd_workbook.py server/cccd_workbook_test.py
```

Expected: the existing one-cell compatibility test and parser change are visible. Save the diff in the task notes; do not reset it.

- [ ] **Step 2: Replace the invented-cell assertion with failing native-extent assertions**

```python
def test_extract_drawings_preserves_one_cell_origin_and_extent(tmp_path):
    book = tmp_path / "one-cell.xlsx"
    _write_synthetic_xlsx(book, [("Cards", [("rId1", "xl/media/image1.png", (7, 2, 8, 3), _PNG)])])
    _replace_zip_part(
        book,
        "xl/drawings/drawing1.xml",
        _one_cell_xml(row=7, col=2, row_off=111, col_off=222,
                      cx=2_476_500, cy=1_524_000, rel_id="rId1"),
    )
    drawing = extract_drawings(str(book), str(tmp_path / "out")).drawings[0]
    assert drawing.anchor == Anchor(
        "Cards", 7, 2, None, None,
        from_row_offset=111,
        from_col_offset=222,
        anchor_type="one-cell",
        extent_cx=2_476_500,
        extent_cy=1_524_000,
)
```

Add `_one_cell_xml` beside the existing synthetic ZIP helpers. It returns a
complete `xdr:wsDr` document containing one `oneCellAnchor`, a native
`<xdr:ext cx="2476500" cy="1524000"/>`, and the supplied relationship ID.

Add malformed tests for missing/zero/negative `cx` or `cy`; each emits `malformed-drawing` and never writes an image record.

- [ ] **Step 3: Run tests and verify failure**

Run: `python3 -m pytest -q server/cccd_workbook_test.py`

Expected: FAIL because `Anchor` has no native type/extent and currently invents `to = from + 1`.

- [ ] **Step 4: Implement the additive anchor model**

```python
@dataclass(frozen=True)
class Anchor:
    sheet: str
    from_row: int
    from_col: int
    to_row: int | None
    to_col: int | None
    from_row_offset: int = 0
    from_col_offset: int = 0
    to_row_offset: int = 0
    to_col_offset: int = 0
    anchor_type: str = "two-cell"
    extent_cx: int | None = None
    extent_cy: int | None = None
```

For `oneCellAnchor`, read the integer `cx` and `cy` attributes from
`<xdr:ext>`, require positive values, store `to_row=None` and `to_col=None`,
and preserve origin offsets. Existing positional `Anchor(...)` calls remain
compatible because new fields are appended with defaults.

- [ ] **Step 5: Run tests and commit the reconciled change**

Run: `python3 -m pytest -q server/cccd_workbook_test.py`

Expected: PASS.

```bash
git add server/cccd_workbook.py server/cccd_workbook_test.py
git commit -m "fix: preserve native CCCD drawing extents"
```

---

### Task 2: Pair one-cell drawings conservatively

**Files:**
- Modify: `server/cccd_pairing.py:24-165`
- Modify: `server/cccd_pairing_test.py`
- Modify: `server/cccd_ingest.py:80-98`
- Modify: `server/cccd_ingest_test.py`

**Interfaces:**
- Consumes: typed `Anchor` values from Task 1.
- Produces: `_same_vertical_band(first, second) -> bool`; serialized native anchor geometry; `unsupported-geometry` candidate issue.

- [ ] **Step 1: Write failing pairing tests**

```python
def test_pairs_one_cell_images_with_same_sheet_and_aligned_origin_rows():
    left = analyzed("left", one_cell("Cards", row=10, col=1, row_off=100, cx=1000, cy=500))
    right = analyzed("right", one_cell("Cards", row=10, col=5, row_off=120, cx=1000, cy=500))
    result = pair_drawings([right, left])
    assert len(result) == 1
    assert result[0].front.drawing.id == "left"
    assert result[0].back.drawing.id == "right"
    assert result[0].issues == ()
```

Add tests that different sheets never pair, different one-cell origin rows
remain singles, same-row extents with less than 50% vertical overlap remain
singles, equal horizontal origin is ambiguous, a one-cell/two-cell mixed
component is `unsupported-geometry`, and three aligned images remain
`ambiguous-pair`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest -q server/cccd_pairing_test.py server/cccd_ingest_test.py
```

Expected: FAIL because overlap arithmetic subtracts `None` or relies on invented extents.

- [ ] **Step 3: Split geometry rules by native anchor type**

```python
def _same_vertical_band(first: Anchor, second: Anchor) -> bool:
    if first.sheet != second.sheet:
        return False
    if first.anchor_type == second.anchor_type == "two-cell":
        return (
            _vertical_overlap_ratio(first, second) >= .5
            or abs(first.from_row - second.from_row) <= 1
        )
    if first.anchor_type == second.anchor_type == "one-cell":
        if first.from_row != second.from_row:
            return False
        return _offset_extent_overlap_ratio(first, second) >= .5
    return False
```

`_offset_extent_overlap_ratio` compares the same-row intervals
`[from_row_offset, from_row_offset + extent_cy]`; Task 1 guarantees positive
extents. Treat mixed native types as separate review candidates with
`unsupported-geometry`; do not infer overlap across incomparable coordinate
models. Continue to use `(from_col, from_col_offset)` for left/front versus
right/back.

- [ ] **Step 4: Serialize the native geometry safely**

```python
{
    "type": anchor.anchor_type,
    "fromRow": anchor.from_row,
    "fromCol": anchor.from_col,
    "fromRowOffset": anchor.from_row_offset,
    "fromColOffset": anchor.from_col_offset,
    "toRow": anchor.to_row,
    "toCol": anchor.to_col,
    "extentCx": anchor.extent_cx,
    "extentCy": anchor.extent_cy,
}
```

Keep this inside the private CCCD workbook result; the compact case response remains aggregate-only.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest -q server/cccd_pairing_test.py server/cccd_ingest_test.py server/cccd_workbook_test.py
```

Expected: PASS.

```bash
git add server/cccd_pairing.py server/cccd_pairing_test.py server/cccd_ingest.py server/cccd_ingest_test.py
git commit -m "fix: pair one-cell CCCD drawings conservatively"
```

---

### Task 3: Version CCCD extraction and attachment results

**Files:**
- Modify: `server/cccd_ingest.py`
- Modify: `server/cccd_ingest_test.py`
- Modify: `server/cases.py:93-111`
- Modify: `server/cases_test.py`
- Modify: `src/upload/api.ts:123-145`
- Modify: `src/upload/api.test.ts`

**Interfaces:**
- Consumes: native geometry and existing pairing/matching results.
- Produces: `CCCD_EXTRACTOR_VERSION = 'ctv-cccd/2.0'`; private workbook `extractorVersion`; compact response `extractorVersion` without mappings or values.

- [ ] **Step 1: Write failing version-provenance tests**

```python
def test_ingest_result_records_cccd_extractor_version(tmp_path, monkeypatch):
    result = _run_synthetic_ingest(tmp_path, monkeypatch)
    assert result["cccdWorkbook"]["extractorVersion"] == "ctv-cccd/2.0"
    compact = compact_cccd_summary(result["cccdWorkbook"])
    assert compact["extractorVersion"] == "ctv-cccd/2.0"
    assert "mappings" not in compact
```

Add a legacy compact-summary test defaulting missing versions to `legacy`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest -q server/cccd_ingest_test.py server/cases_test.py
```

Expected: FAIL because the version field is absent.

- [ ] **Step 3: Add version constants and summaries**

Set the private workbook version on every ready, partial, and error result. Return only the fixed version string through `compact_cccd_summary`; do not expose candidate IDs, OCR values, anchors, or paths.

```python
CCCD_EXTRACTOR_VERSION = "ctv-cccd/2.0"

def _workbook_result(status, summary, **extra):
    return {
        "status": status,
        "extractorVersion": CCCD_EXTRACTOR_VERSION,
        "summary": summary,
        **extra,
    }
```

- [ ] **Step 4: Add the frontend field**

```ts
export interface CccdSummary {
  status: 'ready' | 'partial' | 'error'
  candidates: number
  attached: number
  unresolved: number
  extractorVersion: string
  errorCode?: string
}
```

Normalize legacy responses to `legacy` and add the API test.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest -q server/cccd_ingest_test.py server/cases_test.py
npm test -- --run src/upload/api.test.ts
```

Expected: PASS.

```bash
git add server/cccd_ingest.py server/cccd_ingest_test.py server/cases.py server/cases_test.py src/upload/api.ts src/upload/api.test.ts
git commit -m "feat: version CCCD extraction results"
```

---

### Task 4: Define the private-safe accuracy dataset contract

**Files:**
- Create: `server/accuracy_dataset.py`
- Create: `server/accuracy_dataset_test.py`
- Create: `docs/accuracy-dataset-format.md`

**Interfaces:**
- Consumes: anonymized JSON labels and predictions.
- Produces: `load_accuracy_dataset(path) -> dict`; `load_prediction_dataset(path) -> dict`; fixed validation errors; documented schema versions `ctv-accuracy/1.0` and `ctv-accuracy-predictions/1.0`.

- [ ] **Step 1: Write failing dataset validation tests**

```python
def test_dataset_accepts_anonymized_versioned_records(tmp_path):
    path = write_dataset(tmp_path, {
        "schemaVersion": "ctv-accuracy/1.0",
        "datasetId": "gold-synthetic-v1",
        "cases": [{
            "caseKey": "case-001",
            "expectedPacketStarts": [0, 8],
            "packets": [{
                "packetKey": "packet-001",
                "participantKey": "participant-001",
                "fields": {"cccd": {"valueToken": "id-token-001", "evidence": [0, 10, 10, 20, 8]}},
            }],
        }],
    })
    assert load_accuracy_dataset(path)["datasetId"] == "gold-synthetic-v1"
```

Add rejection tests for real-looking 12-digit CCCD values, names outside fixed opaque-key patterns, absolute paths, duplicate packet/participant keys, out-of-range evidence, unknown schema versions, and unbounded case/packet/field counts.

Add a valid prediction test with `pdfExtractorVersion`,
`cccdExtractorVersion`, predicted packet starts, packet verdicts, opaque
participant/field tokens, evidence boxes, CCCD attachment targets, and
`reviewerSeconds` plus `boundaryCorrections`. Gold records include
`baselineReviewerSeconds` for the same packet. The prediction loader applies
the same privacy and size limits and rejects unknown/missing keys.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/accuracy_dataset_test.py`

Expected: FAIL because the loader does not exist.

- [ ] **Step 3: Implement bounded validation**

Use fixed limits: at most 100 cases, 10,000 packets, 32 fields per packet, 10 evidence boxes per field, and 10 MiB input JSON. Opaque keys must match `^[a-z]+-[0-9]{3,6}$`; value tokens must match `^[a-z]+-token-[0-9]{3,6}$`. Reject absolute paths and strings containing 12 consecutive digits.

```python
MAX_DATASET_BYTES = 10 * 1024 * 1024
MAX_CASES = 100
MAX_PACKETS = 10_000
MAX_FIELDS = 32
MAX_EVIDENCE_PER_FIELD = 10
OPAQUE_KEY = re.compile(r"^[a-z]+-[0-9]{3,6}$")
VALUE_TOKEN = re.compile(r"^[a-z]+-token-[0-9]{3,6}$")
PRIVATE_DIGITS = re.compile(r"\d{12}")
```

Read at most `MAX_DATASET_BYTES + 1`, parse JSON once, dispatch to the gold or
prediction schema validator, validate exact allowed keys and list counts, and
recursively reject strings that contain an absolute path or `PRIVATE_DIGITS`
match. `load_accuracy_dataset` accepts only `ctv-accuracy/1.0`;
`load_prediction_dataset` accepts only `ctv-accuracy-predictions/1.0`.

- [ ] **Step 4: Document the exact format**

Document every gold and prediction field, limit, coordinate order (`[page, x,
y, width, height]`), anonymization rule, and the requirement that local source
PDFs/workbooks remain outside git. Include one complete synthetic example for
each schema that passes its loader.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest -q server/accuracy_dataset_test.py`

Expected: PASS.

```bash
git add server/accuracy_dataset.py server/accuracy_dataset_test.py docs/accuracy-dataset-format.md
git commit -m "feat: define anonymized accuracy dataset contract"
```

---

### Task 5: Compute safety and reviewer-efficiency metrics

**Files:**
- Create: `server/accuracy_metrics.py`
- Create: `server/accuracy_metrics_test.py`

**Interfaces:**
- Consumes: validated gold labels and prediction records.
- Produces: `evaluate_accuracy(gold, predictions) -> dict` with boundary, contamination, field, evidence, false-clear, abstention, CCCD, and reviewer-time metrics.

- [ ] **Step 1: Write failing metric tests with exact expected values**

```python
def test_accuracy_metrics_count_false_clear_and_contamination():
    result = evaluate_accuracy(_gold_two_packets(), _prediction_one_mixed_packet())
    assert result["packetBoundary"] == {
        "truePositive": 1,
        "falsePositive": 0,
        "falseNegative": 1,
        "precision": 1.0,
        "recall": 0.5,
        "exactBatchAccuracy": 0.0,
    }
    assert result["crossPersonContamination"] == 1
    assert result["falseClear"]["count"] == 1
    assert result["falseClear"]["rate"] == 0.5
```

Add exact tests for per-field accuracy, complete-packet accuracy, evidence
IoU/location accuracy, false-clear rate, abstention rate, CCCD attachment
precision, median reviewer seconds, correction count per packet, same-set
reviewer-time improvement, and zero-denominator behavior returning `None`
rather than misleading 0% or 100%.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/accuracy_metrics_test.py`

Expected: FAIL because the metrics module does not exist.

- [ ] **Step 3: Implement deterministic metric helpers**

```python
def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator

def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
```

Use exact opaque participant/field tokens for correctness and IoU >= 0.5 for evidence-location success. Count a false clear when a predicted `match` packet is not a complete correct gold packet or contains another participant's observation.

- [ ] **Step 4: Emit a fixed, aggregate-only result shape**

Include `schemaVersion`, `datasetId`, `pdfExtractorVersion`, `cccdExtractorVersion`, counts, ratios, and release-gate booleans. Do not return per-participant values or evidence boxes.

```python
return {
    "schemaVersion": "ctv-accuracy-result/1.0",
    "datasetId": gold["datasetId"],
    "pdfExtractorVersion": predictions["pdfExtractorVersion"],
    "cccdExtractorVersion": predictions["cccdExtractorVersion"],
    "packetBoundary": boundary_metrics,
    "crossPersonContamination": contamination_count,
    "fieldAccuracy": field_metrics,
    "completePacketAccuracy": complete_packet_accuracy,
    "evidenceLocationAccuracy": evidence_location_accuracy,
    "falseClear": {"count": false_clear_count, "rate": false_clear_rate},
    "abstentionRate": abstention_rate,
    "cccdAttachmentPrecision": cccd_precision,
    "medianReviewerSeconds": reviewer_median,
    "correctionsPerPacket": corrections_per_packet,
    "releaseGates": release_gates,
}
```

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest -q server/accuracy_metrics_test.py server/accuracy_dataset_test.py`

Expected: PASS.

```bash
git add server/accuracy_metrics.py server/accuracy_metrics_test.py
git commit -m "feat: measure extraction safety and accuracy"
```

---

### Task 6: Add the qualification CLI and release gates

**Files:**
- Create: `server/evaluate_accuracy.py`
- Create: `server/evaluate_accuracy_test.py`
- Create: `server/fixtures/accuracy/gold-synthetic-v1.json`
- Create: `server/fixtures/accuracy/predictions-synthetic-v1.json`
- Modify: `server/README.md`

**Interfaces:**
- Consumes: `--gold`, `--predictions`, optional `--json-out`.
- Produces: aggregate JSON to stdout/file; exit 0 only when safety gates pass, exit 2 for validation errors, exit 3 for failed release gates.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_fails_release_when_false_clear_is_nonzero(tmp_path):
    result = run_cli(tmp_path, gold=_gold_file(), predictions=_unsafe_prediction_file())
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["releaseGates"]["zeroFalseClear"] is False
    assert "participant-" not in result.stdout
```

Add tests for a passing fixture, validation error exit 2, atomic JSON output, no path/PII echo, and deterministic byte-identical output for identical inputs.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/evaluate_accuracy_test.py`

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement the CLI**

```python
def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        gold = load_accuracy_dataset(args.gold)
        predictions = load_prediction_dataset(args.predictions)
        result = evaluate_accuracy(gold, predictions)
    except AccuracyDatasetError as error:
        print(json.dumps({"status": "invalid", "code": str(error)}, sort_keys=True))
        return 2
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.json_out:
        _atomic_write(args.json_out, payload.encode("utf-8"))
    print(payload, end="")
    return 0 if all(result["releaseGates"].values()) else 3
```

Release gates are zero cross-person contamination, zero false-clear, complete
evidence provenance, unresolved-to-review compliance, zero wrong-person CCCD
attachment, and improved median reviewer time against the baseline recorded on
the same gold set. Missing baseline timing fails the reviewer-time gate rather
than silently passing it.

- [ ] **Step 4: Add safe synthetic fixtures and usage documentation**

The committed fixture uses only opaque keys/tokens and must pass the dataset loader. Document:

```bash
python3 server/evaluate_accuracy.py \
  --gold server/fixtures/accuracy/gold-synthetic-v1.json \
  --predictions server/fixtures/accuracy/predictions-synthetic-v1.json
```

State explicitly that real local evaluation data is never copied into the
repository. The private gold set must include case-shape tags for
`stable-32-packet`, `heterogeneous-41-roster`, mixed identities, missing covers,
repeated titles, rotation, missing documents, unreadable values, and
multi-sheet CCCD images. Before pilot enablement, run the same CLI on this
reviewer-confirmed private set and retain only the aggregate result JSON.

- [ ] **Step 5: Run focused and full qualification**

Run:

```bash
python3 -m pytest -q server/accuracy_dataset_test.py server/accuracy_metrics_test.py server/evaluate_accuracy_test.py
python3 server/evaluate_accuracy.py --gold server/fixtures/accuracy/gold-synthetic-v1.json --predictions server/fixtures/accuracy/predictions-synthetic-v1.json
python3 -m pytest -q server/cccd_workbook_test.py server/cccd_pairing_test.py server/cccd_ingest_test.py
```

Expected: all tests PASS and the safe synthetic qualification exits 0.

- [ ] **Step 6: Run the complete suite and commit**

Run:

```bash
python3 -m pytest -q server
npm test -- --run
npm run build
```

Expected: all tests PASS and build exits 0. Record any unrelated pre-existing failure without weakening a release gate.

```bash
git add server/evaluate_accuracy.py server/evaluate_accuracy_test.py server/fixtures/accuracy/gold-synthetic-v1.json server/fixtures/accuracy/predictions-synthetic-v1.json server/README.md
git commit -m "feat: qualify extractor releases against safety gates"
```
