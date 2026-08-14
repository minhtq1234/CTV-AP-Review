# Task 3 — Freeze One Approved Preparation Snapshot

## Status

Completed on branch `ver1` from base `441db059ab2dc6131ce8864803c46fecfb48fedf`.
The frozen `ctv-intake-v2` contract tree and its pins were not changed.

## RED / GREEN evidence

RED was captured before production code existed:

```text
python3 -m pytest server/ctv_package_assignment_test.py server/ctv_proposal_test.py server/ctv_inspection_classifier_test.py -q
ModuleNotFoundError: No module named 'ctv_package_assignment'
```

GREEN after the minimal snapshot/parser/assignment implementation:

```text
python3 -m pytest server/ctv_package_assignment_test.py server/ctv_proposal_test.py server/ctv_inspection_classifier_test.py -q
77 passed, 5 warnings
```

Required focused gate (with local-loopback listener permission):

```text
python3 -m pytest server/ctv_package_assignment_test.py server/ctv_proposal_test.py server/ctv_proposal_review_test.py server/ctv_proposal_review_ui_test.py server/ctv_inspection_classifier_test.py -q
85 passed, 5 warnings
```

Additional gates:

```text
python3 -m py_compile server/ctv_package_assignment.py server/ctv_proposal.py
git diff --check
```

Both exited successfully. The complete regression suite was run once with its
loopback tests enabled; JUnit output recorded `tests="1206"`, `errors="0"`,
`failures="0"` in 54.292 seconds.

## Delivered behavior

- Canonical fixed roster-header categories are reduced from bounded private
  worksheet text. Existing public roster readiness remains unchanged, while
  missing, duplicate, blank, or conflicting FA-code conditions are private
  package-consumption blockers.
- A successful normal proposal approval records a private, exact-digest token.
  Selecting a roster or changing any unit/source decision invalidates it.
  Consumption recomputes stricter package readiness, checks the current digest,
  and consumes the token once.
- `ApprovedProposalSnapshot` and its roster, unit-decision, and source-
  disposition components are frozen tuple/dataclass values. Private roster
  values and FA code are excluded from their default representations.
- `build_assignments` produces v2 assignment participants, included-unit
  assignments, exclusions, and deterministic manifest decisions. It requires
  an exact locator set and rejects locator/unit mismatches, an invalid selected
  roster scope, unsupported units, and participant ordering drift.

## Compatibility and privacy review

`approve`, `draft_result`, `cancelled_result`, existing public proposal digest
input, and normal review readiness retain their existing output shapes. The
approval result remains a public result only; it does not carry roster values
or itself grant package consumption. The local-review path continues to expose
only the existing local name plus masked identity display, never FA or the
new canonical roster values. Snapshot repr, assignment JSON, public result
repr, digest input, and rejection messages contain no raw roster/FA data.

## Self-review

I checked the state-machine edges: pre-approval, stale digest, mutation after
approval, second consume, excluded/wrong-scope selected roster, no included
PDF, unresolved decisions, and package-only FA blockers all reject through the
same fixed safe error. Unit/source handling is sorted by opaque numeric IDs,
and decision/row/source identifiers are SHA-256-derived from the proposal
digest and opaque records. No source ownership, writer, transaction, CLI,
validator, builder transform, or WP behavior was added.

## Concerns

No functional blocker. Pytest emits five pre-existing PyMuPDF SWIG deprecation
warnings; all relevant and full-suite test results are passing.
