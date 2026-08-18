# CTV Exception-First Proposal Review Design

**Status:** Approved design
**Date:** 2026-08-18

## Context

The first real pilot inspected 12 source files and produced 536 atomic evidence
units. The existing review UI required 540 individual decisions before approval.
That interaction is not viable: it turns human review into page-by-page data
labeling and makes the amount of user work scale with document size.

The inspection, immutable-source, package-writing, and validation boundaries are
working as intended. The redesign therefore replaces the proposal and review
interaction model while preserving the existing prepared-package contract and
publication guarantees.

## Product decision

The review experience will be exception-first.

- The toolkit automatically organizes groups that pass concrete deterministic
  checks.
- The user reviews only ambiguous, conflicting, missing, unreadable, or
  unsupported evidence.
- Uncertainty blocks only the affected pages or source, not confidently
  organized evidence elsewhere.
- Shared documents are assigned once to the whole case.
- The user gives one final approval covering the complete proposal.

Automatic organization is not independent approval. The final human approval
accepts the complete, fully accounted proposal after every exception is
resolved.

## Goals

- Make user effort scale with exception clusters rather than pages or
  worksheets.
- Preserve exact, deterministic accounting for every inspection unit.
- Select a single strong roster candidate automatically in normal cases.
- Organize participant evidence into meaningful packets and shared case
  documents.
- Give each exception one recommended action and bounded alternatives.
- Preserve local-only processing and privacy-safe WP results.
- Continue using the existing package writer, validator, and v2 contract.

## Non-goals

- The redesign will not change source files.
- It will not publish partial or unapproved packages.
- It will not treat a model confidence percentage as proof of correctness.
- It will not send document contents, participant identities, previews, or
  local paths to WP.
- It will not redesign the prepared-package format.
- It will not add a remote service or require network access.

## Terminology

- **Unit:** One atomic inspection result, such as a PDF page, worksheet, or
  image.
- **Review group:** An ordered set of units sharing one document role and one
  assignment target.
- **Participant packet:** All accepted participant-specific groups associated
  with one roster participant.
- **Shared group:** Evidence assigned once to the whole case.
- **Exception:** Evidence that cannot pass the deterministic automatic
  organization gate.
- **Exception cluster:** Related exceptions that can be understood and resolved
  with one user action.
- **Automatically organized:** A proposed group that passed all required gates
  and needs no individual user action before final approval.
- **User-resolved:** An exception cluster for which the user made an explicit
  decision.

## User experience

### 1. Automatic roster selection

The toolkit ranks structurally valid roster candidates using bounded workbook
signals and participant-row evidence. It selects a roster automatically only
when one candidate is uniquely strongest and internally valid.

No roster-selection step is shown in the normal case. Missing, tied, malformed,
or conflicting candidates create one roster exception. Resolving that exception
recomputes participant packets and downstream exception clusters.

### 2. Review home

The first screen presents operational totals rather than a unit list:

```text
Review required
12 sources · 536 units · 25 participant packets

Automatically organized: 528
Needs your review: 8
Unaccounted: 0
```

The exact numbers depend on the case. The invariant is that the working queue
contains exception clusters, never every atomic unit.

The screen has three sections:

1. **Needs review** — the active exception queue, shown first.
2. **Automatically organized** — collapsed packets and shared groups available
   for optional spot checks.
3. **Coverage and approval** — the final accounting summary and approval action.

### 3. Exception queue

Exceptions are grouped by user problem:

- unmatched participant;
- ambiguous roster;
- mixed packet or uncertain split point;
- missing expected document;
- conflicting participant or document role;
- duplicate evidence;
- unreadable or low-confidence pages;
- unsupported source;
- exclusion requiring human judgment.

Each card shows only the local information required to decide:

- source label and page or worksheet range;
- preview of the affected evidence;
- fixed issue explanation;
- recommended action;
- bounded alternative actions.

Supported actions include accepting the recommendation, assigning to a
participant, assigning to the whole case, changing the role, adjusting a split,
merging adjacent groups, keeping one duplicate, or excluding evidence with a
reason. **Apply to all similar** is available only when the affected clusters
share the same fixed issue type and the same permitted action shape.

Resolving a cluster removes it from the active queue. Users can undo a
resolution before final approval.

### 4. Automatically organized evidence

Automatically organized content is grouped by participant packet and shared
case document. It is collapsed by default and never appears as a flat list of
opaque unit IDs.

Each group summary shows:

- meaningful local label;
- document role;
- page or worksheet range;
- target participant or whole case;
- checks that established automatic eligibility;
- optional preview.

Opening or spot-checking these groups is optional. Editing one converts the
affected group into a user-resolved group and recomputes coverage.

### 5. Final approval

Approval is enabled only when:

- every atomic unit is in exactly one review group or explicit exclusion;
- no exception remains;
- no duplicate assignment exists;
- no hidden or unaccounted page exists;
- roster and participant targets remain valid;
- retained source observations are unchanged;
- the displayed proposal digest matches the proposal being approved.

The final screen summarizes participant packets, shared groups, exclusions,
source coverage, user-resolved exceptions, and automatically organized units.
One action approves the complete proposal.

## Grouping and automatic eligibility

Model and OCR signals may propose group candidates, but automatic eligibility
is determined by versioned rules. A group is automatically organized only when
all applicable checks pass:

- the selected roster is valid and uniquely authoritative;
- the participant identity maps to exactly one roster participant;
- the document role is supported for the target scope;
- source order and page continuity are coherent;
- expected packet structure is satisfied where applicable;
- no unit is shared with another group;
- no conflicting identity or role signal exists;
- source and unit issue codes contain no blocking condition;
- the complete source coverage projection remains valid.

Failure of any required check creates an exception for the smallest safe range.
It does not downgrade unrelated valid ranges from the same source.

Exact byte duplicates may be proposed as deterministic duplicate exclusions.
Semantic or visually similar documents are never excluded automatically.
Unreadable and unsupported sources always require an explicit user decision.

## Shared documents

Contracts, policies, common acceptance material, and other evidence applicable
to the entire case are represented once as whole-case groups. They are not
copied into or repeatedly reviewed under every participant packet.

A shared group may be automatically organized only when its whole-case role is
unambiguous and it contains no participant-specific identity conflict.
Otherwise it enters the exception queue.

## Proposal data model

The proposal retains atomic unit records internally and adds a group projection.
Each review group contains:

- stable opaque group ID;
- ordered member unit IDs;
- source and range references;
- proposed role;
- target scope and participant handles when applicable;
- fixed eligibility check codes;
- state: `automatically-organized`, `exception`, or `user-resolved`;
- user decision metadata only for user-resolved groups;
- blocking issue codes, if any.

The public local review API exposes group and exception projections. It does not
expose raw OCR text or private source paths. Before package construction, the
approved groups expand deterministically into the exact unit assignments and
source dispositions already consumed by the package writer.

The proposal digest covers roster selection, every group membership and order,
roles, targets, exclusions, resolutions, and complete unit coverage.

## Components and data flow

```text
Immutable inspection observation
        ↓
Candidate grouping
        ↓
Deterministic eligibility gate
        ↓
Automatically organized groups + exception clusters
        ↓
Local exception-first review
        ↓
Complete approved group proposal
        ↓
Exact unit-assignment expansion
        ↓
Existing package writer and validator
        ↓
Bounded privacy-safe WP result
```

Logical component responsibilities:

- **Inspection engine:** unchanged; produces bounded atomic evidence.
- **Grouping engine:** creates ordered participant, shared, and exclusion
  candidates without mutating inspection evidence.
- **Eligibility gate:** applies deterministic versioned rules and produces fixed
  check or exception codes.
- **Proposal state:** owns group state, exception resolution, coverage, digest,
  and approval readiness.
- **Review API/UI:** exposes local group summaries, previews, exception actions,
  and final approval.
- **Assignment expansion:** converts the approved group proposal into existing
  unit assignments and source dispositions.
- **Writer and validator:** unchanged except for accepting the expanded result
  through the existing boundary.

## Failure and recovery behavior

- A grouping uncertainty becomes an exception instead of a guessed assignment.
- A bad page blocks only its smallest safe range.
- An unreadable or unsupported file becomes one source-level exception.
- An internal grouping or coverage failure returns a fixed private-safe error
  and produces no package.
- A source mutation invalidates the proposal and all approval state.
- Changing the roster recomputes participant targets and affected groups.
- A failed exception action leaves the previous proposal state intact.
- Closing or cancelling the review returns a draft and writes no package.
- Publication remains atomic and occurs only after approval and validation.

## Privacy and security

- All inspection, grouping, previews, and review remain local.
- Participant display names and identity hints are local-review-only values.
- Public CLI and WP envelopes contain only bounded counts, fixed codes, opaque
  IDs where required, and package status.
- No raw OCR text, cell values, source filenames, local paths, tokens, or
  participant display values enter logs or public results.
- Existing loopback authentication, CSRF, Host/Origin, request-size, timeout,
  and no-write review controls remain mandatory.
- Existing immutable-source and exact-publication validation remains mandatory.

## Accessibility and interaction requirements

- The exception queue is fully keyboard navigable.
- Every action has a text label and is not communicated by color alone.
- Focus moves predictably after a cluster is resolved or undone.
- Counts and readiness changes are announced to assistive technology.
- Preview controls have descriptive labels and preserve readable zoom behavior.
- Batch actions require a clear scope description and reversible confirmation.

## Verification strategy

### Grouping and eligibility tests

- contiguous and noncontiguous page grouping;
- unique, missing, tied, and malformed roster candidates;
- exact participant match and conflicting participant signals;
- supported roles for participant and whole-case scopes;
- shared contract and common-document grouping;
- duplicate, unreadable, unsupported, and low-confidence evidence;
- mixed packet split and merge boundaries;
- deterministic ordering and digest stability;
- no unit present in two groups;
- no unit missing from coverage;
- bounded inputs, outputs, and iteration.

### Proposal and API tests

- automatically organized groups require no individual action;
- only exceptions contribute to the active review count;
- similar-cluster batch actions cannot cross issue or action boundaries;
- edits and roster changes recompute affected groups safely;
- final approval requires zero exceptions and exact coverage;
- mutation at observation close invalidates terminal approval;
- public and log shapes remain privacy-safe.

### UI tests

- initial view opens on exception clusters, not a unit list;
- organized evidence is collapsed and available for spot checks;
- exception actions, undo, split, merge, and batch application work;
- coverage and readiness update after every action;
- keyboard and focus behavior is deterministic;
- the interface remains usable for hundreds or thousands of atomic units.

### End-to-end acceptance

- Generated mixed-source cases pass inspection, grouping, local review,
  expansion, writing, and standalone validation.
- Existing v1 and v2 contract pins remain unchanged.
- Existing package validation and atomic publication suites remain green.
- The real pilot no longer opens with 540 unresolved decisions.

## Pilot success criteria

- User actions equal the number of exception clusters plus final approval, with
  at most one additional action for an ambiguous roster.
- Automatically organized units require no individual confirmation.
- Every one of the 536 pilot units is still exactly accounted for.
- No package is produced while any exception remains.
- A normal case with no exceptions requires one final approval action.
- The final WP result remains bounded and contains no private document content.

## Rollout boundary

This design is implemented as a replacement proposal/review slice behind the
existing local `package prepare` command. The current unit-by-unit screen remains
the reference regression for what must not be exposed to users. A new real-folder
pilot is required before the exception-first workflow is considered ready for a
WP team handoff.
