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

## Fix round 2 — durable incomplete-cleanup signal

Rollback cleanup now reports incomplete attempt-owned asset removal without
leaking file paths or exception text. `_cleanup_attempt_files` returns whether
either its file check or deletion raised. The pre-commit failure path always
returns the existing de-duplicated `attachment-failed` issue and appends the
safe, de-duplicated `cleanup-failed` issue only when cleanup was incomplete.
Normal rollback remains unchanged when cleanup succeeds.

### Fix-round TDD evidence

- RED: the forced-unlink regression failed because rollback returned only
  `attachment-failed`.
- GREEN: focused ingest suite — 65 passed, 5 known third-party warnings.
- CCCD suite — 121 passed, 5 known third-party warnings.
- Full backend — 292 passed, 6 known third-party warnings.
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

## Fix round 1 — reviewer findings

All five in-scope findings were addressed with new tests first.

1. The pre-commit write/copy/build block now ends immediately after successful
   `_atomic_json_write`. Attachment success and stale cleanup run afterwards,
   so malformed stale pages or cleanup errors cannot invoke rollback or delete
   newly referenced assets. The stale scan itself tolerates malformed document
   and page structures.
2. A destination becomes attempt-owned before `copyfile` runs. Partial PNG and
   JPEG copies are removed on failure; rollback deletion is best-effort and an
   unlink failure still produces the safe `attachment-failed` result with the
   original manifest bytes intact.
3. Attachment validates direct plans before I/O: the target and packet index
   must be non-boolean, non-negative integers, both resolution and mapping
   state must be `exact`, and a complete front/back card plus serialized sides
   must be present.
4. Mapping planning clears the target for a missing front or back and retains
   the existing safe `missing-front`/`missing-back` issues. Such candidates are
   ordinary `ready` unresolved results, never attachments or technical partials.
5. Progress reporting is contained; callback failures cannot escape after
   durable attachment work.

### Fix-round TDD evidence

- RED: 9 focused failures demonstrated the five reported paths (malformed
  post-commit cleanup, partial copy, invalid direct plans, missing side, and
  progress callback failure).
- GREEN: `cd server && python3 -m pytest cccd_ingest_test.py -q` — 65 passed,
  5 known third-party warnings.
- CCCD suite: 121 passed, 5 known third-party warnings.
- Full backend: 292 passed, 6 known third-party warnings.
- `git diff --check` — clean.
