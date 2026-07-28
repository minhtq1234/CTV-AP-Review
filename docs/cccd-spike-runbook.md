# CCCD Mapping Viability Spike Runbook

This is a local-only go/no-go experiment. It does not attach a card to a
packet, update a case, call an API, or change the production pipeline. Run it
only with authorized inputs on the local machine. Do not use cloud OCR or any
external service.

## Private inputs

Set these variables to explicit absolute paths outside the repository:

```bash
export CCCD_SPIKE_WORKBOOK="/private/local/path/cards.xlsx"
export CCCD_SPIKE_ROSTER="/private/local/path/roster.xlsx"
export CCCD_SPIKE_GROUND_TRUTH="/private/local/path/cccd-ground-truth.json"
export CCCD_SPIKE_OUTPUT="/private/local/path/cccd-spike-output"
```

The workbook, roster, ground truth, extracted images, OCR observations, and
real run results are private. Never copy or commit them into this repository.
The CLI rejects a ground-truth file located inside the repository.

## Private ground truth

Create the ground truth by manually inspecting the authorized workbook and
roster locally. Drawing IDs are the deterministic IDs assigned by the local
extractor; treat them as opaque. The committed example below is synthetic:

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

Each card entry must have exactly those three fields. Each drawing ID may
appear only once across the file, every drawing ID must exist in the extracted
workbook, every `rosterCccd` must be a string of exactly 12 digits, and truth
CCCD values must be unique.

Audit the source locally before running:

1. Inspect every card image and record its true front and back drawing IDs.
2. Check the corresponding roster identity directly in the authorized roster
   and record the exact 12-digit roster CCCD.
3. Include the drawings needed to evaluate every automatic front/back pair and
   every exact roster resolution. The run fails as invalid input if either
   category lacks ground-truth coverage.
4. After the run, use only the aggregate `false_pairs` and
   `false_exact_matches` counts. Do not export or paste candidate-level,
   drawing-level, OCR, name, or CCCD details into a report or terminal log.

The evaluator compares every proposed pair with the audited front/back pair
and every exact resolution with the audited roster CCCD. A crossed pair counts
as false even when both individual drawings appear elsewhere in ground truth.

## Run

Iteration 1:

```bash
python3 server/cccd_spike.py \
  --workbook "$CCCD_SPIKE_WORKBOOK" \
  --roster "$CCCD_SPIKE_ROSTER" \
  --ground-truth "$CCCD_SPIKE_GROUND_TRUTH" \
  --output-dir "$CCCD_SPIKE_OUTPUT" \
  --iteration 1
```

If and only if iteration 1 returns `revise`, make one focused local
region/OCR revision without weakening the exact-match safety rule, then rerun
the same command with `--iteration 2`. No third iteration is allowed.

## Decision thresholds

All placement rates use one fixed denominator: unique roster identities whose
normalized roster CCCD contains exactly 12 digits. An absent card, failed
extraction, unreadable number, conflict, or unresolved mapping therefore
cannot disappear from the denominator. Zero eligible identities is invalid
input.

A run proceeds only when all six gates pass:

- extraction rate is `1.00`;
- false proposed pairs are `0`;
- false exact roster matches are `0`;
- exact placement rate is at least `0.85`;
- exact placement plus unique-name suggestion rate is at least `0.95`; and
- manual-search rate is at most `0.05`.

Any false proposed pair or false exact roster match returns `stop`
immediately, including on iteration 1. If the safety counts are zero but any
other gate fails, iteration 1 returns `revise`; iteration 2 returns `stop`.
Passing all gates on either allowed iteration returns `proceed`.

## Aggregate output

The CLI prints only `decision` and aggregate `metrics`. It writes
`cccd-spike-report.json` in `CCCD_SPIKE_OUTPUT` with exactly these top-level
keys:

```text
iteration
decision
metrics
thresholds
```

`metrics` contains only aggregate counts and rates:

```text
expected_mappable_identities
supported_drawing_instances
extracted_drawings
proposed_pairs
false_pairs
exact_matches
false_exact_matches
unique_name_suggestions
manual_search
extraction_rate
exact_rate
assisted_rate
manual_search_rate
```

The report never contains input filenames, worksheet names, anchors, drawing
IDs, names, CCCD values, roster rows, candidate records, or OCR text.

Exit codes:

- `0` — `proceed`
- `2` — `revise`
- `3` — `stop`
- `4` — invalid or missing private input, invalid iteration, invariant
  violation, or incomplete audit coverage

Invalid runs print no private error detail and do not write a partial report.

## Cleanup

The CLI creates its extraction directory under `CCCD_SPIKE_OUTPUT` and removes
that temporary directory automatically before returning. After recording the
aggregate decision, delete the entire explicitly configured
`CCCD_SPIKE_OUTPUT` directory and any private scratch extraction or audit
artifacts. Retain the source workbook, roster, and private ground truth only
under the applicable data-retention policy. Never commit real inputs, detailed
results, extracted images, contact sheets, OCR output, or the aggregate real
report.
