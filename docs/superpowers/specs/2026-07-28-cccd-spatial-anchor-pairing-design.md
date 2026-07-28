# CCCD Spatial-Anchor Pairing Design

**Status:** Approved, 2026-07-28

## Purpose

Fix v1 CCCD workbook ingestion for the confirmed workbook convention:

- card fronts and backs are placed next to each other;
- the front is visually left and the back is visually right; and
- images can start in the same Excel cell or differ by one anchor row even
  when they are visually aligned.

The current implementation requires OCR to classify an image as `front` or
`back` before pairing. In the real 61-image workbook, 48 images were
`unknown-side`, producing one pair and 59 unresolved single-image candidates.

This change applies only to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

## Verified Workbook Evidence

The real workbook contains 61 drawings on one worksheet. Excel's drawing XML
order is not spatial: it jumps between distant row bands, so consecutive
drawing-order pairing yields only six valid pairs.

Grouping the same drawings by their spatial row bands yields:

- 29 groups containing exactly two adjacent images;
- 3 groups containing one image; and
- 0 groups containing more than two images.

Some paired images share the same integer `fromCol`. Their `colOff` values are
required to identify which image is visually left.

## Selected Approach

Pair images from their Excel spatial anchors before considering OCR side
classification.

For each worksheet:

1. construct an undirected graph of drawings whose vertical anchors qualify;
2. compute deterministic connected components;
3. pair a component only when it contains exactly two drawings;
4. order those drawings by their full horizontal start anchor; and
5. assign visually left as `front` and visually right as `back`.

A one-drawing component remains unpaired. A component containing more than two
drawings is ambiguous; all members remain unresolved. The algorithm never
guesses among multiple neighbours.

## Anchor Model

Extend `EmbeddedDrawing.anchor` compatibly with optional integer offsets:

```python
Anchor(
    sheet,
    from_row,
    from_col,
    to_row,
    to_col,
    from_row_offset=0,
    from_col_offset=0,
    to_row_offset=0,
    to_col_offset=0,
)
```

Existing five-argument constructors and persisted mappings remain valid.
OOXML extraction reads `rowOff` and `colOff` from both `from` and `to`
markers. Missing offsets normalize to zero.

Full anchor offsets are persisted with unresolved mapping provenance but remain
redacted from the public case-detail response.

## Vertical Grouping

Two drawings are spatial neighbours only when:

1. they belong to the same worksheet; and
2. their integer row spans overlap by at least 50% of the shorter span, or
   their starting rows differ by at most one.

The criterion intentionally matches the confirmed workbook's placement and
existing pairing tolerance. Different worksheets and distant row bands never
join.

Connected components make ambiguity explicit. A three-image overlap does not
produce a best-effort pair.

## Left/Right Assignment

Horizontal order uses the lexicographic start position:

```text
(fromCol, fromColOff)
```

If both drawings have the same full horizontal start, the component is
ambiguous and remains unresolved.

For a valid two-image component:

- left = front;
- right = back; and
- OCR `unknown-side` is accepted for either member.

An explicit OCR contradiction (`left == back` or `right == front`) adds
`layout-side-conflict`. That candidate remains persisted but cannot attach
automatically. OCR never swaps the layout-defined sides.

## Identity and Attachment Safety

Layout determines only which images form one card. It never determines the
person.

Automatic attachment remains allowed only when:

1. the layout-defined front has one located 12-digit CCCD;
2. digit-crop OCR confidence is at least `0.85`;
3. the CCCD matches exactly one eligible roster identity;
4. that roster identity maps to exactly one packet;
5. the pair has no `layout-side-conflict`; and
6. both evidence writes and manifest reconciliation succeed.

Name-only, fuzzy, CMND, low-confidence, duplicate, conflicting, unreadable,
single-image, and ambiguous-layout candidates remain unresolved.

## Data and UI Effects

No API request shape, upload field, packet status, rejection state,
document-view behavior, or public response shape changes.

Candidate count now represents structural cards rather than mostly individual
images. For the verified workbook, the structural result must be exactly:

```text
29 paired candidates + 3 unpaired candidates = 32 candidates
```

The case summary remains:

```text
CCCD: <attached> đã gắn · <unresolved> chưa ghép
```

Existing cases are not mutated automatically. The corrected pairing applies
when a case is processed again from a new upload.

## Failure Handling

- Single-image components remain unresolved with provenance.
- Components larger than two remain unresolved as `ambiguous-pair`.
- Equal horizontal start anchors remain unresolved.
- Explicit OCR/layout disagreement remains unresolved.
- Workbook, OCR, evidence-write, storage-budget, and reconciliation failures
  retain their existing safe behavior.
- No names, CCCD values, OCR text, workbook contents, or image bytes are
  logged.

## Tests

Use synthetic, PII-free fixtures to prove:

1. row-aligned left/right drawings pair when both OCR sides are `unknown`;
2. drawings with a one-row start offset still pair;
3. same-cell drawings use `colOff` to determine left/right order;
4. a one-image component remains unpaired;
5. different worksheets do not pair;
6. distant row bands do not pair;
7. a component with more than two images produces no guessed pair;
8. equal full horizontal starts remain ambiguous;
9. explicit OCR/layout disagreement blocks exact resolution;
10. a layout pair with an exact high-confidence front CCCD still attaches
    through the existing roster and packet gates;
11. old five-argument `Anchor` construction remains compatible; and
12. a sanitized aggregate check of the real workbook anchors yields 29 pairs,
    3 singles, and no ambiguous component without printing PII.

## Acceptance Criteria

- The verified 61-image workbook produces 32 structural candidates: 29 pairs
  and 3 singles.
- `unknown-side` no longer prevents a spatially unambiguous pair.
- Full anchor offsets correctly order images that begin in the same Excel
  column.
- Layout cannot bypass exact CCCD, confidence, unique-roster, unique-packet,
  or evidence-write requirements.
- Ambiguous or contradictory layouts never attach automatically.
- Existing v1 dashboard, rejection, viewer, API, persistence, redaction,
  storage bounds, and PDF-only/roster-only flows remain compatible.
