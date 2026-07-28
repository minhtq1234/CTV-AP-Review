# CCCD Spatial-Anchor Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v1 form CCCD card candidates from the workbook's left/right image layout so the verified 61-image workbook produces 29 pairs plus 3 singles, while retaining exact-only identity attachment.

**Architecture:** Extend the extracted OOXML anchor with native row/column offsets, then replace OCR-side-first pairing with deterministic same-sheet spatial connected components. Layout assigns left as front and right as back; OCR side is only a contradiction signal. The existing matcher and ingest pipeline remain the only identity and attachment gates.

**Tech Stack:** Python 3, OOXML `zipfile`/`ElementTree`, dataclasses, pytest, existing local Pillow/Tesseract OCR, and JSON-on-disk v1 packet manifests. Approved design: `docs/superpowers/specs/2026-07-28-cccd-spatial-anchor-pairing-design.md`.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1` on branch `ver1`.
- Do not modify or depend on v2.
- Do not change API request shapes, public case-detail shapes, upload UI, packet status, rejection, review, reporting, or viewer behavior.
- Layout determines only the two images belonging to a card. It never determines identity.
- Automatic attachment still requires a located exact 12-digit CCCD, digit-crop confidence `>= 0.85`, one unique roster identity, one packet target, both sides, and successful evidence writes/reconciliation.
- Name-only, fuzzy, CMND, low-confidence, duplicate, conflicting, ambiguous-layout, OCR/layout-conflicted, single-image, and unreadable candidates never attach automatically.
- Preserve every candidate and its anchor provenance, including unresolved candidates.
- Missing OOXML offsets normalize to zero; existing five-argument `Anchor(...)` construction must remain valid.
- Never log or commit real names, CCCD values, OCR text, workbook contents, images, manifests, or case data. Tests use synthetic, PII-free values.
- Existing cases are not migrated or mutated. Users must re-upload to process a workbook with the new pairing logic.
- Do not push without an explicit user request.

---

### Task 1: Preserve full OOXML drawing anchors

**Files:**

- Modify: `server/cccd_workbook.py`
- Modify: `server/cccd_workbook_test.py`
- Modify: `server/cccd_ingest.py`
- Modify: `server/cccd_ingest_test.py`

**Interfaces:**

- Extends `Anchor` with four optional integer offsets:
  `from_row_offset`, `from_col_offset`, `to_row_offset`, and
  `to_col_offset`.
- Preserves existing positional order and five-argument constructors.
- Reads `<rowOff>` and `<colOff>` from both OOXML anchor markers.
- Persists offsets in internal mapping provenance using camel-case keys.

- [ ] **Step 1: Add failing backward-compatibility and OOXML offset tests**

In `server/cccd_workbook_test.py`, import `Anchor` and add a direct compatibility
test:

```python
def test_anchor_offsets_default_to_zero():
    anchor = Anchor("Cards", 1, 2, 10, 3)

    assert (
        anchor.from_row_offset,
        anchor.from_col_offset,
        anchor.to_row_offset,
        anchor.to_col_offset,
    ) == (0, 0, 0, 0)
```

Update `_write_synthetic_xlsx` so an anchor accepts either the legacy four
coordinates or all eight coordinates. Four-coordinate fixtures must continue
omitting offset nodes so they prove that missing OOXML offsets normalize to
zero:

```python
if len(anchor) == 4:
    from_row, from_col, to_row, to_col = anchor
    from_row_offset = from_col_offset = 0
    to_row_offset = to_col_offset = 0
    include_offsets = False
else:
    (
        from_row,
        from_col,
        to_row,
        to_col,
        from_row_offset,
        from_col_offset,
        to_row_offset,
        to_col_offset,
    ) = anchor
    include_offsets = True
```

When `include_offsets` is true, emit the offsets inside the correct
`xdr:from` and `xdr:to` nodes:

```xml
<xdr:col>{from_col}</xdr:col>
<xdr:colOff>{from_col_offset}</xdr:colOff>
<xdr:row>{from_row}</xdr:row>
<xdr:rowOff>{from_row_offset}</xdr:rowOff>
```

Keep the existing four-coordinate fixture XML free of `colOff`/`rowOff`.

Add an extraction test using non-zero, distinct values:

```python
def test_extract_drawings_preserves_full_anchor_offsets(tmp_path):
    book = tmp_path / "offsets.xlsx"
    _write_synthetic_xlsx(
        book,
        [("Cards", [(
            "rId1",
            "xl/media/image1.png",
            (7, 2, 18, 4, 111, 222, 333, 444),
            _PNG,
        )])],
    )

    result = extract_drawings(str(book), str(tmp_path / "out"))

    assert result.drawings[0].anchor == Anchor(
        "Cards",
        7,
        2,
        18,
        4,
        from_row_offset=111,
        from_col_offset=222,
        to_row_offset=333,
        to_col_offset=444,
    )
```

- [ ] **Step 2: Add a failing mapping-provenance test**

Extend the `analyzed(...)` helper in `server/cccd_ingest_test.py` with an
optional `anchor` argument. Add:

```python
def test_mapping_provenance_serializes_full_anchor_offsets(tmp_path):
    candidate = card(tmp_path)
    front = replace(
        candidate.front,
        drawing=replace(
            candidate.front.drawing,
            anchor=Anchor(
                "Sheet1",
                1,
                2,
                5,
                6,
                from_row_offset=10,
                from_col_offset=20,
                to_row_offset=30,
                to_col_offset=40,
            ),
        ),
    )
    candidate = replace(candidate, front=front)

    planned = plan_candidate_mappings(
        [candidate],
        resolution(candidate),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
    )[0]

    assert planned.mapping["front"]["anchor"] == {
        "sheet": "Sheet1",
        "fromRow": 1,
        "fromCol": 2,
        "toRow": 5,
        "toCol": 6,
        "fromRowOffset": 10,
        "fromColOffset": 20,
        "toRowOffset": 30,
        "toColOffset": 40,
    }
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest server/cccd_workbook_test.py server/cccd_ingest_test.py -q
```

Expected: failures because `Anchor` does not accept offset keywords and
serialized provenance omits them.

- [ ] **Step 4: Implement compatible offset extraction**

Append defaulted fields after the existing five fields in
`server/cccd_workbook.py`:

```python
@dataclass(frozen=True)
class Anchor:
    sheet: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    from_row_offset: int = 0
    from_col_offset: int = 0
    to_row_offset: int = 0
    to_col_offset: int = 0
```

Keep the existing required coordinate reads strict. Add a default only for
optional offsets:

```python
def _anchor_value(element, side, value, *, default=None):
    node = element.find(f"{_DRAWING_NS}{side}/{_DRAWING_NS}{value}")
    if node is None or node.text is None:
        if default is not None:
            return default
        raise ValueError(f"missing anchor {side}.{value}")
    return int(node.text)
```

Construct the anchor with named offset arguments:

```python
anchor = Anchor(
    sheet_name,
    _anchor_value(element, "from", "row"),
    _anchor_value(element, "from", "col"),
    _anchor_value(element, "to", "row"),
    _anchor_value(element, "to", "col"),
    from_row_offset=_anchor_value(
        element, "from", "rowOff", default=0
    ),
    from_col_offset=_anchor_value(
        element, "from", "colOff", default=0
    ),
    to_row_offset=_anchor_value(
        element, "to", "rowOff", default=0
    ),
    to_col_offset=_anchor_value(
        element, "to", "colOff", default=0
    ),
)
```

Do not make a missing `row`, `col`, or `to` coordinate valid.

- [ ] **Step 5: Persist offsets in internal mapping provenance**

In `server/cccd_ingest.py`, extend only `_serialize_side`:

```python
"anchor": {
    "sheet": anchor.sheet,
    "fromRow": anchor.from_row,
    "fromCol": anchor.from_col,
    "toRow": anchor.to_row,
    "toCol": anchor.to_col,
    "fromRowOffset": anchor.from_row_offset,
    "fromColOffset": anchor.from_col_offset,
    "toRowOffset": anchor.to_row_offset,
    "toColOffset": anchor.to_col_offset,
},
```

No public API adapter changes are required because `app.py` already removes
`cccdWorkbook` from case detail and returns only its aggregate summary.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
python3 -m pytest server/cccd_workbook_test.py server/cccd_ingest_test.py -q
```

Expected: all selected tests pass, including legacy synthetic workbooks that
omit offsets.

- [ ] **Step 7: Commit the anchor foundation**

```bash
git add server/cccd_workbook.py server/cccd_workbook_test.py server/cccd_ingest.py server/cccd_ingest_test.py
git commit -m "feat: preserve CCCD drawing offsets"
```

---

### Task 2: Pair cards from deterministic spatial components

**Files:**

- Modify: `server/cccd_pairing.py`
- Modify: `server/cccd_pairing_test.py`

**Interfaces:**

- `pair_drawings(images) -> list[CardCandidate]` remains unchanged.
- A spatial edge exists only for same-sheet drawings satisfying the approved
  vertical overlap/one-row tolerance.
- Exactly two drawings in a component form one layout pair.
- Components of one remain single candidates; components larger than two
  remain separate ambiguous candidates.
- Full horizontal start `(from_col, from_col_offset)` determines left/right.
- A valid layout pair always stores left in `front` and right in `back`.

- [ ] **Step 1: Replace the old OCR-side behavior tests with approved layout tests**

Update the `analyzed(...)` helper in `server/cccd_pairing_test.py` so the
synthetic anchor can include offsets:

```python
def analyzed(
    drawing_id,
    side,
    *,
    anchor,
    sheet="Cards",
    from_col_offset=0,
):
    from_row, from_col, to_row, to_col = anchor
    return AnalyzedDrawing(
        drawing=EmbeddedDrawing(
            id=drawing_id,
            anchor=Anchor(
                sheet,
                from_row,
                from_col,
                to_row,
                to_col,
                from_col_offset=from_col_offset,
            ),
            media_type="image/png",
            extension="png",
            width=1,
            height=1,
            sha256=f"hash-{drawing_id}",
            stored_path=f"/synthetic/{drawing_id}.png",
        ),
        ocr=CccdImageOcr(
            side=side,
            side_confidence=.99,
            cccd="",
            cccd_confidence=0.0,
            name="",
            name_confidence=0.0,
            number_bbox=None,
        ),
    )
```

Write these literal tests before implementation:

1. Two row-aligned `unknown` drawings pair; left becomes front, right becomes
   back, and `issues == ()`.
2. Start rows differing by one still pair.
3. Two drawings in the same integer column order by `from_col_offset`, even
   when input and drawing IDs are reversed.
4. A singleton preserves current side-specific provenance:
   `front -> missing-back`, `back -> missing-front`,
   `unknown -> unknown-side`.
5. Drawings on different sheets remain separate.
6. Distant row bands remain separate.
7. A connected three-image row group produces three unpaired candidates, all
   with `ambiguous-pair`, and no candidate has both sides.
8. Two drawings with equal `(from_col, from_col_offset)` remain separate with
   `ambiguous-pair`.
9. Left OCR `back` or right OCR `front` creates one pair with
   `layout-side-conflict`; OCR does not swap its layout sides.
10. Candidate IDs and output ordering are deterministic for reversed input.

The core happy-path assertion should be explicit:

```python
def test_pairs_unknown_sides_by_left_right_layout():
    right = analyzed("drawing-0001", "unknown", anchor=(2, 4, 12, 6))
    left = analyzed("drawing-0099", "unknown", anchor=(2, 1, 12, 3))

    result = pair_drawings([right, left])

    assert len(result) == 1
    assert result[0].id == "card-drawing-0099-drawing-0001"
    assert result[0].front is left
    assert result[0].back is right
    assert result[0].unknown is None
    assert result[0].issues == ()
```

Add a generated aggregate fixture with 29 two-image row groups and 3
single-image row groups. Use unique row bands separated by more than one row
and deliberately reverse/shuffle IDs. Assert:

```python
assert len(result) == 32
assert sum(
    candidate.front is not None and candidate.back is not None
    for candidate in result
) == 29
assert sum(
    candidate.front is None or candidate.back is None
    for candidate in result
) == 3
```

- [ ] **Step 2: Run pairing tests and verify RED**

Run:

```bash
python3 -m pytest server/cccd_pairing_test.py -q
```

Expected: the unknown-side, offset-ordering, component ambiguity, and
aggregate tests fail under OCR-side-first pairing.

- [ ] **Step 3: Build deterministic same-sheet components**

Remove the mutual-nearest and distance-margin code from
`server/cccd_pairing.py`; it is no longer part of the approved algorithm.
Retain `_vertical_overlap_ratio`.

Introduce:

```python
def _vertically_eligible(
    first: AnalyzedDrawing,
    second: AnalyzedDrawing,
) -> bool:
    first_anchor = first.drawing.anchor
    second_anchor = second.drawing.anchor
    if first_anchor.sheet != second_anchor.sheet:
        return False
    return (
        _vertical_overlap_ratio(first_anchor, second_anchor) >= .5
        or abs(first_anchor.from_row - second_anchor.from_row) <= 1
    )


def _spatial_components(
    images: list[AnalyzedDrawing],
) -> list[list[AnalyzedDrawing]]:
    ordered = sorted(images, key=lambda item: item.drawing.id)
    neighbours = {
        image.drawing.id: set()
        for image in ordered
    }
    by_id = {image.drawing.id: image for image in ordered}
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if _vertically_eligible(first, second):
                neighbours[first.drawing.id].add(second.drawing.id)
                neighbours[second.drawing.id].add(first.drawing.id)

    components = []
    visited = set()
    for image in ordered:
        if image.drawing.id in visited:
            continue
        pending = [image.drawing.id]
        component = []
        while pending:
            drawing_id = pending.pop()
            if drawing_id in visited:
                continue
            visited.add(drawing_id)
            component.append(by_id[drawing_id])
            pending.extend(sorted(
                neighbours[drawing_id] - visited,
                reverse=True,
            ))
        components.append(sorted(
            component,
            key=lambda item: item.drawing.id,
        ))
    return components
```

Reject duplicate drawing IDs up front rather than silently overwriting
`by_id`:

```python
if len({image.drawing.id for image in images}) != len(images):
    raise ValueError("duplicate drawing id")
```

- [ ] **Step 4: Convert components into safe candidates**

Use the full horizontal start:

```python
def _horizontal_start(image: AnalyzedDrawing) -> tuple[int, int]:
    anchor = image.drawing.anchor
    return anchor.from_col, anchor.from_col_offset
```

Refactor the existing singleton behavior into a helper that can accept a
forced issue:

```python
def _single_candidate(
    image: AnalyzedDrawing,
    issue: str | None = None,
) -> CardCandidate:
    if image.ocr.side == "front":
        return CardCandidate(
            f"card-{image.drawing.id}",
            image,
            None,
            (issue or "missing-back",),
        )
    if image.ocr.side == "back":
        return CardCandidate(
            f"card-{image.drawing.id}",
            None,
            image,
            (issue or "missing-front",),
        )
    return CardCandidate(
        f"card-{image.drawing.id}",
        None,
        None,
        (issue or "unknown-side",),
        image,
    )
```

Make each component deterministic:

```python
def _component_candidates(
    component: list[AnalyzedDrawing],
) -> list[CardCandidate]:
    if len(component) != 2:
        issue = "ambiguous-pair" if len(component) > 2 else None
        return [_single_candidate(image, issue) for image in component]

    first, second = sorted(
        component,
        key=lambda image: (
            _horizontal_start(image),
            image.drawing.id,
        ),
    )
    if _horizontal_start(first) == _horizontal_start(second):
        return [
            _single_candidate(image, "ambiguous-pair")
            for image in component
        ]

    issues = (
        ("layout-side-conflict",)
        if first.ocr.side == "back" or second.ocr.side == "front"
        else ()
    )
    return [CardCandidate(
        id=f"card-{first.drawing.id}-{second.drawing.id}",
        front=first,
        back=second,
        issues=issues,
    )]
```

Then `pair_drawings` flattens components and sorts by candidate ID:

```python
def pair_drawings(images: list[AnalyzedDrawing]) -> list[CardCandidate]:
    if len({image.drawing.id for image in images}) != len(images):
        raise ValueError("duplicate drawing id")
    candidates = [
        candidate
        for component in _spatial_components(images)
        for candidate in _component_candidates(component)
    ]
    return sorted(candidates, key=lambda candidate: candidate.id)
```

Do not use OCR side to create, swap, or choose between pairs.

- [ ] **Step 5: Run pairing tests and verify GREEN**

Run:

```bash
python3 -m pytest server/cccd_pairing_test.py -q
```

Expected: all spatial grouping, ambiguity, contradiction, determinism, and
29-pair/3-single tests pass.

- [ ] **Step 6: Commit spatial pairing**

```bash
git add server/cccd_pairing.py server/cccd_pairing_test.py
git commit -m "feat: pair CCCD images by spatial anchors"
```

---

### Task 3: Keep exact matching safe for layout-defined fronts

**Files:**

- Modify: `server/cccd_matching.py`
- Modify: `server/cccd_matching_test.py`
- Modify: `server/cccd_ingest_test.py`

**Interfaces:**

- A layout-defined `front` may have OCR side `front` or `unknown`.
- `ambiguous-pair` and `layout-side-conflict` are blocking pair issues.
- Blocked candidates neither resolve nor claim a roster target that could
  incorrectly conflict with another valid candidate.

- [ ] **Step 1: Add failing matcher tests**

Update the `candidate(...)` helper in `server/cccd_matching_test.py` to accept
`ocr_side: str = "front"` and use it in `CccdImageOcr`.

Add:

```python
def test_layout_front_with_unknown_ocr_side_can_resolve_exact():
    result = resolve_candidates(
        [candidate(
            "c1",
            cccd="000000000001",
            cccd_conf=.95,
            ocr_side="unknown",
        )],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "exact"
    assert result.resolutions[0].matched_by == "cccd"
```

Add a contradiction test:

```python
def test_layout_side_conflict_blocks_exact_match():
    result = resolve_candidates(
        [candidate(
            "c1",
            cccd="000000000001",
            cccd_conf=.99,
            issues=("layout-side-conflict",),
        )],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    assert result.resolutions[0].state == "conflict"
    assert "layout-side-conflict" in result.resolutions[0].issues
```

Add a two-candidate test proving a blocked candidate does not poison the valid
candidate's uniqueness:

```python
def test_blocked_layout_candidate_does_not_claim_valid_target():
    result = resolve_candidates(
        [
            candidate(
                "blocked",
                cccd="000000000001",
                cccd_conf=.99,
                issues=("layout-side-conflict",),
            ),
            candidate(
                "valid",
                cccd="000000000001",
                cccd_conf=.99,
            ),
        ],
        [{"name": "Synthetic A", "cccd": "000000000001"}],
    )

    by_id = {
        resolution.candidate_id: resolution
        for resolution in result.resolutions
    }
    assert by_id["blocked"].state == "conflict"
    assert by_id["valid"].state == "exact"
```

Retain the existing `ambiguous-pair` test.

- [ ] **Step 2: Add failing layout-to-attachment integration tests**

Extend the concrete `analyzed(...)` helper signature with
`anchor: Anchor | None = None`, then replace its hard-coded anchor expression
with:

```python
anchor=anchor or Anchor("Sheet1", 1, 1, 5, 5),
```

Keep legacy front fixtures working while allowing a layout-defined unknown
front to carry a located number:

```python
number_bbox=(
    {"x": 20, "y": 30, "width": 200, "height": 40}
    if side == "front" or cccd
    else None
),
```

Create two drawings whose IDs arrive in the opposite order from their visual
placement. The left image has OCR side `unknown` but an exact high-confidence
CCCD:

```python
def test_ingest_attaches_exact_unknown_side_pair_by_layout(
    tmp_path,
    monkeypatch,
):
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    left = analyzed(
        tmp_path,
        "drawing-0099",
        "unknown",
        cccd=CCCD,
        confidence=.95,
        anchor=Anchor("Sheet1", 10, 0, 20, 1),
    )
    right = analyzed(
        tmp_path,
        "drawing-0001",
        "unknown",
        anchor=Anchor("Sheet1", 10, 1, 20, 2),
    )
    monkeypatch.setattr(
        cccd_ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(
            2,
            [right.drawing, left.drawing],
            [],
        ),
    )
    ocr_by_id = {
        left.drawing.id: left.ocr,
        right.drawing.id: right.ocr,
    }
    monkeypatch.setattr(
        cccd_ingest,
        "analyze_drawing",
        lambda drawing, *args: ocr_by_id[drawing.id],
    )

    result = ingest_cccd_workbook(
        str(tmp_path / "cards.xlsx"),
        [{"name": "Synthetic A", "cccd": CCCD}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )

    assert result["cccdWorkbook"]["summary"] == {
        "candidates": 1,
        "attached": 1,
        "unresolved": 0,
    }
    mapping = result["cccdWorkbook"]["mappings"][0]
    assert mapping["candidateId"] == (
        "card-drawing-0099-drawing-0001"
    )
    assert mapping["front"]["drawingId"] == "drawing-0099"
    assert mapping["back"]["drawingId"] == "drawing-0001"
    assert mapping["attachedPacketIndex"] == 0
```

Add the same setup with the left image classified as OCR `back`. Assert that
the contradiction survives in provenance and causes no write:

```python
assert result["cccdWorkbook"]["summary"]["attached"] == 0
assert result["cccdWorkbook"]["summary"]["unresolved"] == 1
assert mapping["state"] == "conflict"
assert "layout-side-conflict" in mapping["issues"]
assert mapping["attachedPacketIndex"] is None
assert not [
    document
    for document in json.loads(
        manifest_path.read_text(encoding="utf-8")
    )["docs"]
    if document["id"].startswith("cccd-excel-")
]
```

- [ ] **Step 3: Run matcher and integration tests and verify RED**

Run:

```bash
python3 -m pytest server/cccd_matching_test.py server/cccd_ingest_test.py -q
```

Expected: unknown-side layout front is `manual`, layout conflict can resolve
exactly, the blocked candidate competes with the valid candidate, the exact
layout pair does not attach, and the conflict is not safely blocked.

- [ ] **Step 4: Centralize blocking pair issues**

In `server/cccd_matching.py`, add:

```python
_BLOCKING_PAIR_ISSUES = frozenset({
    "ambiguous-pair",
    "layout-side-conflict",
})


def _blocking_pair_issue(candidate: CardCandidate) -> str | None:
    return next(
        (
            issue
            for issue in candidate.issues
            if issue in _BLOCKING_PAIR_ISSUES
        ),
        None,
    )
```

Layout, not OCR's side label, defines the candidate's front:

```python
def _front_ocr(candidate: CardCandidate):
    return candidate.front.ocr if candidate.front is not None else None
```

Prevent blocked candidates from participating in target-claim conflict
calculation:

```python
def _candidate_claims(candidate, by_cccd, by_name) -> set[int]:
    if _blocking_pair_issue(candidate) is not None:
        return set()
    ocr = _front_ocr(candidate)
    # existing exact/name claim logic follows unchanged
```

In `_resolve_one`, perform the blocking check after confirming a front exists
but before identity parsing:

```python
ocr = _front_ocr(candidate)
if ocr is None:
    return _manual(candidate.id, issues, "no-front")
if blocking_issue := _blocking_pair_issue(candidate):
    return _conflict(candidate.id, issues, blocking_issue)
```

This must not change confidence, exact-digit, duplicate roster, duplicate name,
competing valid candidate, or packet-target behavior.

- [ ] **Step 5: Run matcher and integration tests and verify GREEN**

Run:

```bash
python3 -m pytest server/cccd_matching_test.py server/cccd_ingest_test.py -q
```

Expected: all existing matching safety tests, the three new matcher tests, the
exact layout attachment test, and the conflict no-write test pass.

- [ ] **Step 6: Commit matcher safety and integration coverage**

```bash
git add server/cccd_matching.py server/cccd_matching_test.py server/cccd_ingest_test.py
git commit -m "fix: gate spatial CCCD matches safely"
```

---

### Task 4: Validate the verified workbook structurally and regress all of v1

**Files:**

- No production file changes expected.
- Read-only local input:
  `server/data/cases/741808dc863a4d929624261508a3c6c8/cccd.xlsx`
  if that case still exists.

- [ ] **Step 1: Run a PII-free aggregate structural check**

Use the production extractor against the saved workbook, then replace OCR with
synthetic `unknown` results so the diagnostic prints only structural counts:

```bash
PYTHONPATH=server python3 - <<'PY'
import tempfile

from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, pair_drawings
from cccd_workbook import extract_drawings

source = (
    "server/data/cases/"
    "741808dc863a4d929624261508a3c6c8/"
    "cccd.xlsx"
)
with tempfile.TemporaryDirectory() as output:
    extracted = extract_drawings(source, output)
    unknown = CccdImageOcr(
        side="unknown",
        side_confidence=0.0,
        cccd="",
        cccd_confidence=0.0,
        name="",
        name_confidence=0.0,
        number_bbox=None,
    )
    candidates = pair_drawings([
        AnalyzedDrawing(drawing, unknown)
        for drawing in extracted.drawings
    ])
    pairs = sum(
        candidate.front is not None and candidate.back is not None
        for candidate in candidates
    )
    singles = len(candidates) - pairs
    ambiguous = sum(
        "ambiguous-pair" in candidate.issues
        for candidate in candidates
    )
    print({
        "drawings": len(extracted.drawings),
        "candidates": len(candidates),
        "pairs": pairs,
        "singles": singles,
        "ambiguous": ambiguous,
    })
PY
```

Expected exact aggregate:

```text
{'drawings': 61, 'candidates': 32, 'pairs': 29, 'singles': 3, 'ambiguous': 0}
```

If the local case no longer exists, report the missing fixture rather than
reconstructing or committing user data. The synthetic 29+3 test remains the
repeatable CI acceptance test.

- [ ] **Step 2: Run the full backend and splitter suite**

First run the complete focused CCCD suite so failures stay easy to localize:

```bash
python3 -m pytest \
  server/cccd_workbook_test.py \
  server/cccd_pairing_test.py \
  server/cccd_matching_test.py \
  server/cccd_ingest_test.py \
  server/cccd_ocr_test.py \
  -q
```

Expected: all focused tests pass.

Then run the full regression suite:

Run:

```bash
python3 -m pytest server splitter -q
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend regression tests and production build**

No frontend code changes are expected, but validate that shared case behavior
remains intact:

```bash
npm test
npm run build
```

Expected: all Vitest tests pass and Vite production build exits zero.

- [ ] **Step 4: Inspect scope and safety**

Run:

```bash
git status --short
git diff --check
git diff --stat HEAD~4
git log -5 --oneline
```

Confirm:

- no real workbook, image, OCR output, case JSON, or CCCD value is staged;
- no v2 file changed;
- no public response or frontend file changed;
- anchor fields remain backward compatible;
- old cases were not mutated;
- only the approved spec/plan and v1 backend/test files are in scope.

- [ ] **Step 5: Restart v1 backend and perform a clean re-upload smoke**

Restart only the v1 backend on `127.0.0.1:8001`; keep the v1 frontend on
`127.0.0.1:5174`. Verify `/api/health`, load the case list, and create a new
test case through the existing upload flow using the PDF, roster, and CCCD
workbook.

Do not infer success from the old `741808...` case because existing cases are
not recalculated. The re-uploaded case should report 32 CCCD candidates; the
attached count may be lower than 29 because identity OCR and exact roster gates
remain intentionally conservative.

- [ ] **Step 6: Request an independent code review**

Use `superpowers:requesting-code-review` and ask the reviewer to verify:

- the implementation matches the approved spatial-anchor design;
- component formation cannot guess within ambiguous layouts;
- offset parsing is safe and compatible;
- `unknown` OCR sides can resolve only on the layout-defined front;
- blocked candidates cannot attach or poison valid identity claims;
- exact/confidence/unique roster/unique packet/evidence gates remain intact;
- the real-workbook diagnostic prints aggregate counts only.

Address any high- or medium-severity finding using
`superpowers:receiving-code-review`, rerun all affected tests, and repeat the
full verification before completion.

## Completion Criteria

- Full OOXML anchor offsets are extracted and persisted internally.
- Existing five-argument `Anchor` callers remain green.
- Synthetic acceptance yields 29 pairs and 3 singles.
- The saved verified workbook, when available, yields exactly 61 drawings, 32
  candidates, 29 pairs, 3 singles, and 0 ambiguous candidates without OCR or
  PII output.
- Layout-defined fronts with OCR side `unknown` can pass the unchanged exact
  identity gates.
- Ambiguous or OCR/layout-conflicted candidates never attach.
- Focused CCCD tests, the complete backend/splitter suite, frontend tests, and
  production build all pass.
- A newly uploaded v1 case uses the new logic; old cases remain unchanged.
- Independent review has no unresolved high- or medium-severity findings.
