# Task 5 report — atomic CCCD attachment and resilient ingest

## Scope

- Implemented only `server/cccd_ingest.py` and `server/cccd_ingest_test.py`.
- Added this handoff report. No pipeline, API, CaseStore, frontend, or Phase 0
  module was changed.
- `cccd_spike` is neither imported nor called.

## Strict TDD evidence

### Attachment cycle

1. Added attachment, preservation, rollback, idempotency, packet-mismatch,
   content-addressed filename, checklist, and stale-file tests first.
2. RED: `python3 -m pytest cccd_ingest_test.py -q` produced 12 expected
   failures because `attach_planned_mapping`, `_atomic_json_write`, and its
   dependencies did not yet exist. The 30 existing planner tests remained
   green.
3. Implemented atomic manifest replacement, containment validation,
   content-addressed copying, stable document ownership, source replacement,
   checklist regeneration, and rollback.
4. GREEN: 42 focused tests passed.

### Orchestrator cycle

1. Added ready, partial extraction/OCR/attachment, safe error, progress,
   manual-ready, and malformed metadata tests first.
2. RED: focused tests produced 9 expected failures because the Phase 0
   boundary imports and `ingest_cccd_workbook` did not exist.
3. Implemented extraction → independent OCR → pairing → exact resolution →
   plan → attachment orchestration, with only safe result codes.
4. GREEN: 51 focused tests passed.

### Follow-up regression

Self-review found that an error deleting a stale file after successful
`os.replace` must not report a false attachment failure. Added a test first
(RED: one assertion failed), then made stale-file cleanup best-effort after
the durable manifest commit. Final focused count: 52 passed.

## Final verification

- `cd server && python3 -m pytest cccd_ingest_test.py -q` — 52 passed,
  5 known third-party warnings.
- `cd server && python3 -m pytest cccd_workbook_test.py cccd_ocr_test.py
  cccd_pairing_test.py cccd_matching_test.py cccd_ingest_test.py -q` — 108
  passed, 5 known third-party warnings.
- `cd server && python3 -m pytest -q` — 279 passed, 6 known third-party
  warnings (FastAPI/Starlette deprecation plus the existing SWIG warnings).
- `git diff --check` — clean.

## Self-review

- Attachment leaves a non-target manifest byte-identical and returns a deep
  copy; target/malformed failures do not mutate the manifest.
- New file paths and returned packet paths are contained under the case root;
  filenames derive from candidate and image SHA-256 values, never user names.
- Front/back CCCD docs and the mapped front source are stable and idempotent;
  original docs, source order, and unrelated manifest keys remain intact.
- The manifest is replaced only after a flushed/fsynced same-directory temp
  write. Newly created images are removed on all pre-commit failures; stale
  images are removed only after the replacement.
- Coordinator error messages are never included in durable results. Technical
  priority is attachment, extraction, then OCR; ordinary unresolved mappings
  remain `ready`.

## Concern

Stale-file deletion is intentionally best-effort after the manifest commit:
the committed manifest is authoritative, and a filesystem cleanup failure can
leave an unreferenced `cccd-*` image for later cleanup rather than incorrectly
claiming attachment failure or rolling back a committed manifest.
