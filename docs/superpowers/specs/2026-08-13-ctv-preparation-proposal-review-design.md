# CTV Preparation Proposal Review Design

**Date:** 2026-08-13  
**Status:** Approved for implementation  
**Base:** local `ver1` after safe document inspection (`e9f86ab`)  
**Prior design:** `docs/superpowers/specs/2026-08-13-ctv-safe-document-inspection-design.md`

## 1. Decision

Extend the standalone CTV local toolkit with one interactive, read-only command:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py \
  proposal review \
  --source-root /explicit/local/source \
  --json
```

The command creates a fresh descriptor-bound inspection, starts one temporary
loopback review screen, lets the user map every source/unit to an explicit
participant/case disposition, validates the proposal, and obtains final approval
inside that local screen. It returns one bounded privacy-safe JSON envelope to the
WP agent after the session ends.

This milestone does **not** write a prepared package. It creates no draft, report,
cache, thumbnail, extracted-text file, or application state. It performs no
non-loopback network access. WP contains no CTV code; WP only calls this explicit local script
and explains the bounded result.

The previously discussed external stdin `proposal validate` and WP-mediated
approval flow are superseded by the local screen. Proposal validation remains a
pure internal component, and final approval is authoritative only when the user
performs it locally against the displayed digest summary.

## 2. Goals and non-goals

### Goals

- keep participant names, roster values, source previews, filenames, and document
  content on the user's machine and outside WP model context;
- require one authoritative roster worksheet selected explicitly by the user;
- derive deterministic opaque participant handles such as `participant-0001`;
- account for every inspection unit and every source-only record;
- support individual, explicit shared, and case-level assignments;
- allow drafts with unresolved work without representing them as ready;
- bind final approval to the unchanged source observation and deterministic
  proposal digest;
- return only a bounded canonical JSON result;
- preserve the existing read-only/no-network/source-immutability guarantees.

### Non-goals

- writing, copying, renaming, merging, splitting, or converting source files;
- creating the prepared intake package or validation report;
- persisting or resuming a local review draft;
- proving user identity, document authenticity, evidence ownership, completeness,
  payment readiness, or payment approval;
- exposing private participant labels or document previews to WP;
- adding a WP plugin, bundled CTV skill, remote service, database, or dependency;
- changing the checked-in `contracts/ctv-intake/v1` snapshot.

## 3. User and system flow

1. WP runs `version`, `doctor`, and `contract verify` against the same explicit
   toolkit checkout and stops on failure.
2. WP calls the exact `proposal review` command with one explicit source root.
3. The toolkit opens one secure content-bound inventory observation and performs
   inspection while that observation remains live.
4. The toolkit binds a temporary HTTP server to `127.0.0.1` on an OS-assigned port,
   creates cryptographically random bootstrap/session/CSRF tokens, and opens the
   system browser.
5. The browser shows the approved hybrid workspace:
   - participant and scope navigation on the left;
   - local evidence preview in the center; and
   - role, target, exclusion, and unresolved controls on the right.
6. The user explicitly selects one authoritative roster worksheet. The toolkit
   derives local participant labels and opaque participant handles from that
   worksheet only.
7. The user resolves assignments or explicitly requests a safe draft summary.
8. For final approval, the toolkit validates the complete proposal and computes a
   deterministic digest. The browser shows the final local summary and digest.
9. The user clicks **Approve proposal** locally. The toolkit recomputes the digest,
   requires the unchanged observation, and accepts only an exact match.
10. The local server stops, sensitive in-memory state is released, the retained
    observation performs final tree revalidation, and only then does the CLI emit
    its JSON envelope.

Any source-tree change makes the operation fail. No partial proposal is emitted
after an operational failure.

## 4. Command and exit contract

The exact accepted invocation is:

```text
proposal review --source-root SOURCE --json
```

Missing, abbreviated, duplicated, reordered, empty, option-like, or extra tokens
are invalid. Invalid invocation exits `1`, writes no stdout, and emits only fixed
bounded guidance on stderr without echoing caller input.

The CLI envelope keeps schema version `1.0` and adds operation
`proposal.review`.

| Result | Envelope status | Exit | Meaning |
|---|---|---:|---|
| `approved` | `succeeded` | 0 | Locally approved complete proposal; `readyToPrepare: true`. |
| `draft` | `succeeded` | 0 | Safe summary only; unresolved or not approved; `readyToPrepare: false`. |
| `cancelled` | `succeeded` | 0 | Explicit local cancel/close; no proposal assignments returned. |
| controlled operational failure | `failed` | 2 | Source/environment/session problem; no partial proposal. |
| invalid invocation/internal failure | none or `failed` | 1 | Usage failure or fixed internal boundary. |

Controlled proposal error codes are fixed and ordered:

- `proposal-source-changed`
- `proposal-roster-unavailable`
- `proposal-browser-unavailable`
- `proposal-session-timeout`
- `proposal-session-failed`
- `proposal-output-too-large`

Existing inspection/inventory controlled codes retain their current mapping when
the underlying fresh observation cannot be established.

## 5. Public result model

### 5.1 Approved result

An approved result has this closed shape:

```json
{
  "proposalVersion": "1.0",
  "outcome": "approved",
  "observationId": "observation-<64 lowercase hex>",
  "proposalDigest": "proposal-<64 lowercase hex>",
  "readyToPrepare": true,
  "rosterUnitId": "unit-0001",
  "participants": [
    {"participantHandle": "participant-0001"}
  ],
  "sourceDispositions": [
    {
      "evidenceId": "evidence-0007",
      "decision": "excluded",
      "exclusionReason": "irrelevant"
    }
  ],
  "assignments": [
    {
      "unitId": "unit-0002",
      "decision": "accepted",
      "role": "identity-front",
      "target": {
        "scope": "individual",
        "participantHandles": ["participant-0001"]
      }
    }
  ],
  "totals": {
    "sources": 3,
    "sourceOnly": 1,
    "participants": 1,
    "units": 2,
    "accepted": 1,
    "reassigned": 1,
    "excluded": 1,
    "unresolved": 0,
    "issues": 0
  },
  "issueCodes": [],
  "approval": {
    "status": "user-approved",
    "approvedProposalDigest": "proposal-<64 lowercase hex>"
  }
}
```

All sequences use deterministic order: inspection source/unit order, participant
roster-row order, and approved fixed-code order. Extra keys are rejected at every
input/model boundary.

### 5.2 Draft result

A draft contains no participant list, source dispositions, assignments, local
labels, notes, or preview data:

```json
{
  "proposalVersion": "1.0",
  "outcome": "draft",
  "observationId": "observation-<64 lowercase hex>",
  "readyToPrepare": false,
  "totals": {
    "sources": 3,
    "sourceOnly": 1,
    "participants": 1,
    "units": 2,
    "accepted": 0,
    "reassigned": 0,
    "excluded": 0,
    "unresolved": 3,
    "issues": 1
  },
  "issueCodes": ["proposal-unresolved"]
}
```

### 5.3 Cancelled result

```json
{
  "proposalVersion": "1.0",
  "outcome": "cancelled",
  "readyToPrepare": false
}
```

## 6. Proposal rules

### 6.1 Authoritative roster and participants

- The local screen lists worksheet units with the inspection
  `roster-column-pattern` signal as roster candidates.
- The user must explicitly select exactly one candidate, even when there is only
  one candidate.
- The selected unit must still belong to the current observation and must have
  `unitKind: worksheet`.
- Private bounded extraction uses the same immutable workbook snapshot and the
  existing safe OOXML/decompression/parser boundaries.
- The header row must contain exact recognized `name` and `identity` categories.
  Participant rows begin after that header and are bounded to 10,000 rows and the
  existing workbook cell/text limits.
- Each usable participant row requires one non-empty bounded local display name
  and one normalized identity key. The identity value is never returned to WP or
  written to logs/files.
- Duplicate identity keys, duplicate normalized name/identity pairs, malformed
  rows, or limit failures produce fixed local issues and prevent approval.
- Handles are assigned in usable roster-row order as `participant-0001`,
  `participant-0002`, and so on. They are observation-scoped and must not be
  interpreted as stable identities across runs.
- The browser displays local names and row context only. The public result returns
  handles only.

### 6.2 Unit assignments

Every inspection unit appears exactly once in the proposal.

Allowed decisions:

- `accepted`: selected role exactly equals the inspection suggestion;
- `reassigned`: selected role differs from the suggestion;
- `excluded`: no role or target; one fixed exclusion reason is required;
- `unresolved`: no role or target and always blocks readiness.

Allowed roles are the existing fixed inspection taxonomy and must also be valid
for the unit kind. `unknown` is allowed only with decision `unresolved`; it can
never be approved.

Allowed assignment targets:

- `individual`: exactly one participant handle;
- `shared`: at least two distinct participant handles in roster order;
- `case`: no participant handles.

`shared` never means all participants implicitly. The user must choose every
participant. Evidence applying to the whole submission uses `case`.

### 6.3 Source-only dispositions

Every inspection source with zero or unknown units must appear exactly once in
`sourceDispositions`. This includes opaque archives, unsupported files,
unreadable/encrypted/over-limit documents, symlinks, and special entries.

Allowed decisions are:

- `excluded`, with one fixed exclusion reason; or
- `unresolved`, which blocks readiness.

Source-only items cannot be assigned to a participant, shared group, case role,
or document role because no safe authoritative unit exists.

### 6.4 Exclusion reasons

The closed reasons are:

- `duplicate`
- `irrelevant`
- `unreadable-replacement-available`
- `intentionally-omitted`
- `other`

The local UI may accept a bounded private note when `other` is selected, but the
note remains in memory, is excluded from the digest and public result, and is
reduced to the fixed code `other`.

### 6.5 Readiness

`readyToPrepare` is true only when all conditions hold:

- one authoritative roster is valid;
- at least one participant exists;
- every unit has `accepted`, `reassigned`, or `excluded`;
- every source-only record is `excluded`;
- no selected role is `unknown`;
- every target references current participants and satisfies its cardinality;
- no fixed blocking proposal issue remains;
- the observation and proposal are unchanged; and
- the user locally approved the exact recomputed digest.

Inspection confidence and issue codes never auto-approve a unit. The user must
make an explicit decision for every unit, including high-confidence suggestions.

## 7. Digest and approval

The proposal digest is:

```text
proposal- + lowercase_hex(
  SHA-256(UTF-8(canonical JSON of approval payload))
)
```

The canonical approval payload contains exactly:

- `proposalVersion`
- `observationId`
- `rosterUnitId`
- opaque participant handles in roster order
- source dispositions in source order
- assignments in unit order
- deterministic totals and fixed issue codes

It excludes local participant labels, roster values, filenames, previews, private
notes, session tokens, timestamps, `proposalDigest`, and `approval`.

Approval is a two-pass operation inside the local session:

1. validate the current state and compute the digest;
2. display the local final summary and digest;
3. receive the local approve action;
4. rebuild and revalidate the proposal from current state;
5. recompute the digest and require exact equality;
6. bind `approval.status = user-approved` to that digest.

Any change invalidates approval. This proves consistency, not the user's legal
identity; the toolkit records no approver name, timestamp, or signature.

## 8. Retained observation and private capabilities

The review session owns one live `InventoryObservation` context for its complete
lifetime. Inspection, roster extraction, local preview, proposal validation, and
final tree revalidation use that same descriptor-bound observation.

The session exposes no raw observation descriptor or general filesystem path to
the browser. Internal capabilities are narrow:

- return public inspection result;
- return private roster candidates and selected-roster participant labels;
- return one bounded local preview for a known current unit;
- validate one bounded decision update;
- build a privacy-safe public result.

Snapshot bytes are short-lived, held in memory, and cleared/released after parser
use. The session emits no stdout until the observation context has closed and
final revalidation succeeds.

## 9. Local review server

### 9.1 Binding and authentication

- Bind IPv4 `127.0.0.1` only on an OS-assigned ephemeral port.
- Generate at least 256 bits of entropy for a one-time bootstrap token, session
  token, and CSRF token.
- The initial URL carries only the bootstrap token. A successful bootstrap sets
  an `HttpOnly; SameSite=Strict` session cookie and redirects to a clean URL.
- Every state/preview/action request requires the exact session cookie.
- Every mutation also requires exact same-origin validation and the CSRF token.
- Reject unexpected Host, Origin, method, content type, path, query, body shape,
  duplicate key, and extra key values.
- All responses set `Cache-Control: no-store`, `Pragma: no-cache`,
  `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, and a restrictive Content Security Policy with no
  external origin.

The threat model excludes hostile code already executing as the same OS user or
inside the same Python interpreter. It does not rely on browser UI secrecy for
that excluded attacker.

### 9.2 Browser API

The single-use server supports only these bounded operations:

- bootstrap and load the static local UI;
- get privacy-local review state;
- get one bounded preview for a current unit;
- select the authoritative roster;
- set one unit decision;
- set one source-only disposition;
- request draft summary;
- request approval summary/digest;
- approve the unchanged digest;
- cancel; and
- send a heartbeat.

No arbitrary file endpoint, directory listing, URL fetch, path parameter, shell
command, upload, template evaluation, or WebSocket is allowed.

### 9.3 Lifecycle and bounds

- One CLI invocation owns one session and one browser.
- Session state is memory-only and cannot be resumed.
- Maximum total session duration: 2 hours.
- Maximum idle duration without heartbeat/action: 5 minutes.
- Maximum JSON request body: 1 MiB.
- Maximum API JSON response: 16 MiB.
- Maximum preview response: 25 MiB.
- Existing inspection, workbook, PDF, image, OCR, source, unit, and output limits
  remain binding.
- Explicit Cancel and a verified close signal return `cancelled`.
- User-selected **Return draft summary** returns `draft`.
- Total/idle timeout returns controlled `proposal-session-timeout`, not a draft.
- Browser-launch failure returns `proposal-browser-unavailable`.
- Server/internal/session failure returns a fixed failure with no partial proposal.
- On every terminal outcome, stop accepting requests, close the server, clear
  private state, close the retained observation, and revalidate the source tree.

## 10. Local previews

Previews are generated only for a unit in the current inspection result.

- PDF page: reuse the existing bounded PDF parser/resource proof and render the
  selected page to bounded in-memory PNG.
- Standalone image: reuse the existing bounded image header/decode path and return
  a normalized bounded in-memory PNG.
- Worksheet: use the safely normalized workbook snapshot and return a bounded
  local table view containing at most 200 rows, 50 columns, and 256 characters per
  cell within the existing workbook-wide cell/text limits.

The browser receives private preview data only over the authenticated loopback
session. Responses are no-store and never included in the public result. Preview
failure affects that unit locally and blocks approval until the user resolves or
excludes it according to the proposal rules; no private parser diagnostic is
returned.

## 11. Outcome and recovery behavior

### Approved

Returns the complete privacy-safe approved proposal. It remains only a proposal;
the later preparation milestone must rebind it to the same source observation or
explicitly require a fresh review.

### Draft

Returns only safe totals and fixed issues. No assignments or participant handles
are returned. The draft is not persisted and cannot be resumed. Retry starts with
a fresh inspection and new identifiers.

### Cancelled

Returns only the fixed cancelled result. Closing the browser, pressing Cancel, or
declining the review produces no assignments.

### Failed

Source mutation, invalid retained capability, parser boundary, local-server error,
browser-launch error, timeout, or output-bound failure produces one fixed failure
envelope. It never returns a partial draft or approved proposal.

## 12. Privacy and side-effect boundary

The following must never enter stdout, stderr, routine logs, WP context, public
models, proposal digest input except where explicitly opaque, or committed test
fixtures:

- source paths, filenames, and directory names;
- participant names and roster cell values;
- identity, tax, bank, amount, date, address, and contact values;
- raw embedded text, OCR output, formulas, worksheet names, and private notes;
- rendered images, thumbnails, PDF objects, workbook XML, or parser diagnostics;
- session/bootstrap/CSRF tokens, cookies, browser URLs, and local port values;
- raw exceptions, tracebacks, commands, environment values, usernames, or
  repository paths.

Synthetic tests may use obviously fake markers but must verify they do not cross
public boundaries.

The command creates no document/output/temp/cache/draft/report files and makes no
non-loopback network request. Python bytecode writing remains disabled before
source-backed imports. Browser opening is the only external application side
effect and is intrinsic to the explicitly requested command.

## 13. Components

The implementation uses focused modules:

- `ctv_proposal_model.py`: immutable closed public proposal values, canonical
  digest payload, readiness invariants, bounded serialization;
- `ctv_proposal_validator.py`: pure validation/composition from inspection,
  participants, source dispositions, and unit decisions;
- `ctv_proposal_roster.py`: private bounded authoritative-roster extraction and
  opaque handle derivation;
- `ctv_proposal_preview.py`: private bounded unit preview generation;
- `ctv_proposal_session.py`: retained observation ownership, private state,
  state transitions, approval recheck, and final outcome;
- `ctv_proposal_server.py`: loopback bootstrap/session/CSRF HTTP boundary and
  lifecycle;
- `ctv_proposal_review_ui.py`: dependency-free static local hybrid UI bytes;
- `ctv_intake_cli.py` and `ctv_cli_protocol.py`: exact command, envelope, and
  bounded emission;
- `server/README.md`: WP handoff, privacy guarantees, failure semantics, and
  explicit non-approval/non-preparation boundary.

Existing inspection and inventory modules may receive only narrow context-manager
or preview helper interfaces needed to keep one observation live. They must not
expose descriptors, paths, private parser state, or a general raw-file API.

## 14. Testing and acceptance

Acceptance requires generated synthetic documents only and includes:

- model invariants, canonical order, digest determinism, deep immutability, exact
  primitives, extra-key rejection, and output-size edges;
- every assignment scope/decision/cardinality/role/unit-kind rule;
- exact accounting of all units and source-only records;
- roster selection, participant row order, duplicates, malformed rows, strict and
  transitional OOXML, hidden sheets, and parser/decompression limits;
- digest invalidation for every mutable proposal field and observation change;
- approval recheck after the summary step and before emission;
- draft/cancelled privacy shapes and no assignment leakage;
- authenticated bootstrap, cookie, CSRF, Host/Origin/method/content-type/body
  rejection, headers, no cache, token replay, and single-use shutdown;
- loopback-only binding, random-port use, browser-launch failure, explicit cancel,
  close, idle timeout, total timeout, and server failure cleanup;
- preview authentication, unit binding, PDF/image/worksheet bounds, and no private
  diagnostics;
- descriptor ownership, exact once-close, mutation during inspection/review/
  preview/approval, and final source-tree revalidation;
- no filesystem writes, no source changes, no external sockets, no subprocesses
  except existing bounded local OCR, and no private stdout/stderr/log content;
- exact CLI argv, exit codes, canonical JSON-only stdout, output cap, lazy imports,
  fixed internal failure, and all legacy CLI behavior;
- generated end-to-end smoke: synthetic roster + PDF/image → local decisions →
  digest summary → local approval → privacy-safe JSON, with source tree byte-for-
  byte unchanged;
- full Python suite, frontend suite, production build, `git diff --check`, scope,
  placeholder, privacy, and deterministic-output checks.

No real customer file, name, identity, tax identifier, account, or amount is used
or committed.

## 15. Deferred next milestone

The next separately approved milestone may accept an approved proposal and write a
prepared package into an explicit separate output root. That milestone must define
fresh-observation rebinding, collision behavior, atomic writes, cleanup, provenance,
rollback, validation, and user confirmation. Nothing in this design authorizes or
implements those writes.
