# Task 6 report — pipeline CCCD ingest integration

## Scope

- Modified only `server/pipeline.py` and `server/pipeline_test.py`, plus this
  handoff report.
- The pipeline imports `ingest_cccd_workbook` directly, invokes it only for a
  supplied CCCD workbook, and does not read or write `case.json`.
- `cccd_spike` is neither imported nor called.

## Strict TDD evidence

1. Added the no-CCCD regression test and the supplied-CCCD integration test
   before changing production code. The latter asserts that every manifest is
   already on disk; verifies normalized roster rows, complete manifest paths,
   case/assets directories, and the original progress callback; and returns a
   coordinator-safe `ocr-unavailable` error as ordinary result data.
2. RED: `cd server && python3 -m pytest pipeline_test.py -q` produced the
   expected single failure: the supplied CCCD workbook was ignored and the
   fake coordinator had zero calls. The remaining 13 tests passed.
3. Implemented the minimal bridge: normalize roster rows once after reading,
   emit the initial `cccd` progress event after the packet loop, build paths
   for all completed manifests, and return the coordinator's packet/workbook
   result without rewriting safe errors.
4. GREEN: the same focused pipeline suite passed 14 tests. A post-green
   test-only tightening verifies that the direct import and the exact original
   progress callback remain patchable and passed again.

## Final verification

- `cd server && python3 -m pytest pipeline_test.py -q` — 14 passed, 5 known
  third-party SWIG warnings.
- `cd server && python3 -m pytest pipeline_test.py app_test.py
  cccd_ingest_test.py -q` — 94 passed, 6 known warnings (the existing FastAPI
  / Starlette deprecation plus SWIG warnings).
- `cd server && python3 -m pytest -q` — 293 passed, 6 known warnings.
- `git diff --check` — clean.

## Self-review

- Legacy PDF-only and PDF-plus-roster paths retain their packet metadata,
  manifests, matching/index behavior, and `cccdWorkbook: None` result when
  no workbook is supplied.
- Every generated packet manifest is written during the packet loop before
  CCCD ingest receives the index-to-manifest map.
- The bridge sends normalized `all_roster_rows` values rather than raw
  spreadsheet rows, the case directory, `cccd-assets` directory, and the
  original callback in the required positional order.
- Coordinator errors remain its safe data result; pipeline code does not
  reinterpret them or add exception conversion.
- No `case.json` ownership, API, store, frontend, or Phase 0 spike boundary
  changed.

## Concern

Direct callers can still supply a CCCD workbook without a roster; the
pipeline passes an empty normalized roster to the coordinator, whose safe
result remains data. The API validation introduced earlier prevents that
combination in normal case creation.
