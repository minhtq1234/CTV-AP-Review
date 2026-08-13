# CTV Preparation Proposal Review — Lean V1 Design

**Date:** 2026-08-14  
**Status:** Approved for implementation  
**Base:** local `ver1` after safe document inspection and proposal design planning

## Decision

Build the agreed user workflow, with engineering effort concentrated at the real
trust boundaries:

```text
WP agent
  -> runs local `ctv-intake proposal review`
  -> toolkit inspects the selected folder read-only
  -> temporary local hybrid review screen opens
  -> user selects the roster, reviews assignments, and approves locally
  -> toolkit returns bounded privacy-safe JSON to WP
```

The local screen uses the selected C layout: participant navigation on the left,
document evidence in the center, and assignment controls on the right.

This milestone does not create a prepared package or persist a draft.

## V1 threat boundary

### Defend against

- malformed or hostile browser/API requests;
- cross-origin requests, missing/invalid session and CSRF tokens, token replay;
- arbitrary paths, unit IDs, roles, decisions, participant handles, and JSON
  fields supplied over HTTP;
- source-folder mutation while review is active;
- malformed/oversized PDFs, images, and workbooks using the existing bounded
  inspection controls;
- output/resource exhaustion at documented limits;
- private data leaking through CLI JSON, stderr, logs, or fixed errors;
- filesystem writes, non-loopback network access, and partial approval results.

### Do not defend against in v1

- malicious Python code already executing inside the toolkit process;
- reflection into private module state or closures;
- `object.__setattr__` mutation of trusted internal frozen dataclasses;
- a hostile same-OS-user process reading this process's memory;
- cryptographic proof of the human user's legal identity.

Internal objects constructed after strict API validation are trusted. Tests must
not turn excluded same-process attacks into release blockers.

## User flow

The exact public command is:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py \
  proposal review --source-root /explicit/local/source --json
```

1. WP runs `version`, `doctor`, and `contract verify`, then calls the command.
2. The toolkit opens one retained descriptor-bound observation and runs the
   existing inspection.
3. A temporary server binds to `127.0.0.1` on an OS-assigned port and opens the
   system browser with a one-time bootstrap token.
4. The user explicitly selects one roster worksheet candidate.
5. The toolkit reads bounded participant rows locally and maps them to opaque
   handles `participant-0001`, `participant-0002`, and so on.
6. Every inspected unit is accepted, reassigned, excluded, or unresolved. Every
   source-only item is excluded or unresolved.
7. Assignments target one participant, an explicit set of at least two
   participants, or the entire case.
8. The local summary shows counts, assignments, exclusions, issues, and a
   deterministic proposal digest.
9. The user approves that unchanged summary locally.
10. The server stops, the observation revalidates, and the CLI returns one
    bounded result.

## Outcomes

- `approved`: complete locally approved proposal; `readyToPrepare: true`.
- `draft`: safe counts and issue codes only; `readyToPrepare: false`.
- `cancelled`: fixed outcome only; no assignments.
- controlled failure: fixed error and no partial proposal.

Draft state is memory-only and cannot be resumed. Retry starts from a fresh
inspection.

## Proposal rules

- The authoritative roster must be an inspected worksheet with the existing
  roster signal and must be selected explicitly.
- Participant handles follow usable roster-row order. Names and identity values
  stay local and never appear in CLI JSON.
- Each unit appears exactly once.
- Allowed decisions: `accepted`, `reassigned`, `excluded`, `unresolved`.
- Allowed roles are the existing inspection taxonomy and unit-kind restrictions.
- `unknown` stays unresolved and blocks approval.
- Individual targets contain exactly one handle; shared targets contain at least
  two explicit distinct handles; case targets contain none.
- Source-only items cannot be assigned as evidence units.
- Fixed exclusion reasons: `duplicate`, `irrelevant`,
  `unreadable-replacement-available`, `intentionally-omitted`, `other`.
- Every high-confidence suggestion still needs an explicit user decision.
- Approval is possible only when every unit/source-only item is resolved and the
  source observation is unchanged.

The deterministic digest covers the observation ID, selected roster unit,
participant handles, unit assignments, source dispositions, fixed issue codes,
and counts. It excludes names, roster values, filenames, previews, private notes,
tokens, ports, and timestamps. Any edit invalidates the displayed digest.

## Local web boundary

- Bind only `127.0.0.1` with a random OS port.
- Use a one-time bootstrap token, session cookie, and CSRF token generated with
  `secrets`.
- Validate exact Host, Origin, method, content type, route, JSON key set, primitive
  type, ID format, enum, and body size at every HTTP boundary.
- Use no-store/no-referrer/nosniff/frame-deny headers and a self-only CSP.
- Serve only fixed UI/API routes; no arbitrary file route, upload, proxy, template
  evaluation, WebSocket, or directory listing.
- Do not log request values, tokens, URLs, paths, private errors, or bodies.
- Session duration is at most 2 hours; idle timeout is 5 minutes; JSON request is
  at most 1 MiB; JSON result at most 16 MiB; preview at most 25 MiB.
- On cancel, draft, approval, timeout, or failure: stop the server, clear state,
  close/revalidate the observation, then emit CLI JSON.

## Review data and previews

Use the existing inspection observation and bounded parser helpers. Do not create
a second independent hardening framework.

- Roster: use the selected workbook snapshot and bounded OpenPyXL/read-only data
  access after the existing workbook safety checks. Read at most 10,000 rows,
  100,000 cells, and 256 characters per cell. Require recognized name and identity
  columns. Duplicate/invalid participant rows block approval with fixed local
  issues.
- PDF preview: reuse the existing proved PDF page renderer at or below the current
  150-DPI/50M-pixel/25-MiB limits.
- Image preview: reuse the existing bounded normalized PNG path.
- Worksheet preview: return at most 200 rows by 50 columns, 256 characters per
  cell, within the existing workbook limits.

Preview data travels only over the authenticated loopback session and is never
part of the CLI result.

## Public result

Approved JSON contains only:

- version and outcome;
- `observationId` and deterministic `proposalDigest`;
- `readyToPrepare`;
- selected opaque `rosterUnitId`;
- opaque participant handles;
- opaque unit/evidence IDs;
- fixed decisions, roles, scopes, exclusion reasons, issue codes;
- bounded counts; and
- fixed local-approval status.

Draft JSON contains only version, outcome, observation ID, readiness false,
bounded counts, and fixed issues. Cancelled JSON contains only version, outcome,
and readiness false.

This result is a proposal, not proof of authenticity, completeness, ownership,
payment readiness, payment approval, or user identity.

## Components

Keep v1 to three focused slices:

1. `ctv_proposal.py`: trusted internal proposal state, strict conversion from
   validated API primitives, roster mapping, readiness, digest, and public result.
2. `ctv_proposal_review.py` + `ctv_proposal_review_ui.py`: retained observation,
   previews, memory-only session, loopback HTTP boundary, and hybrid UI.
3. `ctv_intake_cli.py` + protocol/docs: exact command, lifecycle, error mapping,
   bounded emission, and WP handoff.

No new dependency, contract snapshot, frontend product screen, WP bundle, output
writer, database, or persistence layer is introduced.

## Testing and review

Use TDD and generated synthetic files. Required tests focus on:

- strict HTTP/API input validation and authorization;
- normal proposal rules, exact accounting, digest invalidation, and privacy-safe
  public shapes;
- roster mapping and bounded previews;
- source mutation, timeout, cancel/draft/approval cleanup, no writes, and no
  non-loopback access;
- exact CLI invocation, exit codes, lazy imports, canonical output, and legacy
  behavior;
- one real generated end-to-end browser smoke with zero console errors and an
  unchanged source tree;
- full Python tests, frontend tests, production build, diff/scope/privacy checks.

Review process: one task review per slice, one final whole-feature review, one
final correction wave if needed, then one end-to-end acceptance run. Reviewers
must apply the explicit v1 threat boundary and must not block on malicious trusted
same-interpreter object mutation.

## Deferred

Writing a prepared package remains a separate milestone requiring an explicit
output root, atomic/collision behavior, rollback, provenance, validation, and a
new user approval.

