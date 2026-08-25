# Packet Boundary Safety and Correction Design

**Date:** 2026-08-20  
**Last reviewed:** 2026-08-25
**Status:** approved design; Stage 1 decision-surface guard implemented,
publication gate and Stages 2-4 pending

## Problem

The current splitter treats a recurring visual top-band cluster as packet
boundaries. On a heterogeneous batch, a signature page can resemble that
cluster more closely than the first page of a contract. The result can be a
packet that contains the end of one participant, all of another participant,
and the start of a third.

The existing safeguards are incomplete:

- `length-out-of-range`, `near-threshold`, and `auto-merged` flags are stored,
  but a successful CCCD match can still look like a healthy packet.
- the dashboard's AI result currently evaluates document completeness and
  field comparisons without treating boundary uncertainty as a blocking input;
- the reviewer has no explicit packet-boundary warning or correction workflow;
- rewriting one packet in place would damage neighboring packets and could
  detach existing review decisions from their evidence.

The stored evaluation cases demonstrate that this is a boundary failure before
it is an OCR-character failure. The earlier stable batch had 32 roster rows,
32 detected packets, and exactly one contract start in every packet. The later
heterogeneous batch had 41 roster rows but only 36 detected packets; 25 of
those 36 packet ranges contained two or three detected contract starts. The
PDF extractor, pipeline orchestrator, and visual splitter were byte-identical
between the stable checkpoint and the later run. The input exposed an existing
single-signal assumption rather than a replacement OCR implementation.

## Goal

Prevent an uncertain packet boundary from being shown or exported as valid,
and provide a reviewer-confirmed way to create corrected packet boundaries
without altering the original upload or silently moving reviewed evidence.

Boundary resolution is a prerequisite for participant-level extraction. A
packet with unresolved cross-person evidence may retain candidate observations
for review, but those candidates must not be treated as one participant's
field set or used to produce a business validity result.

## Non-goals

- Do not let an LLM autonomously decide or apply packet boundaries.
- Do not mutate an existing case's page ranges in place.
- Do not transfer field-level review decisions to a corrected packet unless the
  evidence mapping is proven identical; corrected packets start unreviewed.
- Do not hardcode page numbers, participant names, or identity values from a
  sample batch.
- Do not replace the existing packet creation, OCR, review, report, or prepared-
  package flows.
- Do not force the number of proposed packets to equal the roster count when
  source evidence does not support those boundaries.
- Do not treat OCR-engine confidence as proof that a value belongs to the
  participant assigned to the packet.

## Delivery stages

### Stage 1: safety guard for current and future cases — partially implemented

Derive a packet boundary assessment from evidence already available in the
case and manifest. An unresolved boundary assessment has precedence over
document and field verdicts:

- dashboard `Kết quả AI` is `Cần review`;
- the row displays `Nghi ngờ nhiều hồ sơ trong một gói` for a strong multi-
  packet signal, otherwise the existing specific boundary reason;
- the packet reviewer displays a persistent warning above the evidence panes;
- the packet counts as needing attention, but not as `cần gửi lại` because a
  boundary problem is an internal processing issue rather than a request for
  the participant to resubmit documents;
- it cannot be presented as `Hợp lệ`, even when one extracted CCCD matches the
  roster.
- reports retain the unresolved-boundary warning and prepared-package
  publication is blocked until the boundary is resolved.

This stage must work for existing stored cases without re-running OCR. Existing
pipeline flags are enough to block false clearance. Manifest evidence can make
the warning more specific when repeated contract documents are available.

The implemented subset derives response metadata, prevents a clear AI result,
and displays the warning. Report retention and prepared-package publication
blocking remain required before Stage 1 is complete. Stage 1 protects the
decision surface but does not repair contaminated stored field candidates.
Existing unresolved packets therefore remain review-only until a reviewer
accepts their current grouping or creates a corrected case revision.

### Stage 2: boundary proposal and reviewer confirmation

For newly processed or explicitly reprocessed cases, retain page-level boundary
evidence produced during OCR. Combine that evidence into a case-level proposal.
The reviewer can inspect the affected ranges, adjust proposed starts, and either
confirm corrected boundaries or explicitly keep the current grouping.

Confirming corrected boundaries creates a new case revision from the preserved
source PDF and roster. The original case remains unchanged and linked as the
source revision. The normal OCR, roster matching, review, report, and prepared-
package flows then operate on the new case.

### Stage 3: identity-isolated extraction

For new and corrected revisions, extraction runs only after a candidate page
range passes the boundary gate or is reviewer-confirmed. Within that range,
the extractor groups observations by document and participant identity before
roster reconciliation:

- each observation retains document ID, page, bounding box, raw candidate
  value, OCR confidence, and extractor version;
- a participant assignment requires one unique roster target supported by an
  exact CCCD or a sufficiently specific normalized-name fallback;
- the highest-confidence candidate is never allowed to choose between two
  conflicting participant identities;
- conflicting identities or ambiguous roster targets return `cannot_assess`;
- only observations assigned to the resolved participant enter field
  comparison and the package evidence grid.

This changes the processing order from `split -> extract everything -> choose
one identity` to `propose boundary -> resolve one participant -> extract and
compare that participant's evidence`.

### Stage 4: CCCD geometry and accuracy qualification

CCCD workbook ingestion remains a separate evidence source. A `oneCellAnchor`
must retain its OOXML origin and actual `ext` dimensions; it must not be
represented as an invented one-row/one-column box. Front/back pairing uses the
preserved geometry, sheet identity, and explicit ambiguity handling. Automatic
attachment still requires an exact 12-digit CCCD, a unique roster/packet
target, both sides, no side conflict, and successful evidence writes.

Stage 4 also establishes the versioned evaluation dataset and release gates
described under Accuracy measurement.

## Approaches considered

### 1. Continue using visual top-band similarity only

Rejected. It is fast, but the observed failure is intrinsic to the signal:
signature pages and contract covers can share recurring header geometry.

### 2. Automatically split on OCR contract titles

Rejected. OCR can miss a title or classify a body-page mention as a title. A
wrong automatic cut can corrupt two neighboring packets and is more dangerous
than an explicit review state.

### 3. Evidence fusion with reviewer confirmation

Selected. Visual similarity remains a cheap candidate signal, while OCR title
anchors, identity changes, normal page cadence, roster count, and existing
pipeline flags establish whether review is required. Deterministic rules create
a proposal; a person approves any boundary rewrite.

## Data model

### Packet response

Add a response-only `boundaryAssessment` to `PacketMeta`:

```ts
type BoundaryReason =
  | 'length-out-of-range'
  | 'near-threshold'
  | 'auto-merged'
  | 'multiple-contract-starts'
  | 'multiple-identities'
  | 'batch-count-mismatch'

interface PacketBoundaryAssessment {
  status: 'clear' | 'review' | 'accepted'
  suspectedMultiplePackets: boolean
  reasons: BoundaryReason[]
  candidateStarts: number[] // zero-based absolute PDF pages, sorted and unique
}
```

For legacy cases, the backend derives the assessment from stored packet flags,
page count, batch count, and manifest document starts. Missing evidence never
produces `clear` when a blocking flag is present.

`accepted` means a reviewer explicitly kept the current grouping. It preserves
the reasons for audit/display but no longer blocks the ordinary AI result or
publication. The UI labels it `Ranh giới đã xác nhận`; it never silently becomes
an evidence-free `clear` assessment.

### Page-level extraction evidence

Extend `ocr_packet`'s internal result with boundary evidence; do not expose OCR
text or identity values through the case-list API:

```py
{
    "contract_starts": [
        {
            "relative_page": 5,
            "title_detected": True,
            "name_key": "normalized-or-empty",
            "cccd_key": "digits-or-empty",
        }
    ]
}
```

The pipeline converts relative pages to absolute PDF pages. Persist only the
minimum derived evidence needed for review. Raw OCR text remains in memory and
PII is not logged.

### Case boundary proposal

Store the proposal separately from packet review snapshots:

```ts
interface CaseBoundaryProposal {
  status: 'not_needed' | 'review_required' | 'accepted_current' | 'superseded'
  sourceCaseId: string
  expectedPacketCount: number | null
  currentPacketCount: number
  candidateStarts: Array<{
    page: number
    signals: Array<'visual' | 'contract-title' | 'identity-change' | 'cadence'>
    confidence: 'high' | 'medium'
  }>
  affectedPacketIndexes: number[]
  affectedRanges: Array<{
    packetIndex: number
    startPage: number
    endPage: number
  }>
}
```

`affectedRanges` contains only valid affected packet ranges. Its page bounds
are inclusive and zero-based, and its entries contain no source paths, OCR
text, identity values, or other participant data. The reviewer may inspect and
toggle any page in these ranges, including a page with no detector signal.

An accepted-current resolution also stores `resolvedAt` and the exact candidate
starts that were reviewed. The local prototype has no authenticated reviewer
identity, so it must not invent or persist a reviewer name.

### Participant extraction result

The resolved or candidate packet result records whether field comparison is
permitted:

```ts
interface ParticipantExtractionResult {
  status: 'ready' | 'review' | 'cannot_assess'
  packetRevision: number
  extractorVersion: string
  rosterTargetKey: string | null
  identityConflict: boolean
  observations: Array<{
    fieldKey: string
    docId: string
    page: number
    bbox: { x: number; y: number; width: number; height: number }
    value: string
    confidence: number
  }>
}
```

`rosterTargetKey` is the source workbook hash plus the zero-based canonical
roster-row index; it is not a display name or logged PII. `ready` is required
before observations can feed `evalField`. `review` retains evidence for human
inspection. `cannot_assess` is a valid terminal extraction state and cannot be
converted to `match` by a single high-confidence observation. The existing
three-state user-facing AI result maps it to `review` with the specific reason
`Không thể đánh giá tự động`; it does not add a fourth dashboard state.

Candidate starts use zero-based absolute PDF pages internally and are displayed
as one-based pages in the UI.

## Deterministic assessment rules

### Stage 1 legacy-safe rules

A packet requires boundary review when any of these are true:

1. it has `length-out-of-range`, `near-threshold`, or `auto-merged`;
2. its manifest contains two or more distinct contract document starts;
3. the richer extractor reports two or more distinct participant identities;
4. the batch packet count differs from a non-null roster count and this packet
   is one of the cadence/length anomalies associated with the gap.

`suspectedMultiplePackets` is true for rule 2 or 3, or when a packet is longer
than the accepted range and contains an internal contract start. A mere batch
count mismatch does not stamp every packet as suspect.

### AI-result precedence

The packet result is derived in this order:

1. boundary assessment with `status: 'review'` -> `review` (`Cần review`);
2. missing required documents or deterministic field mismatch -> `mismatch`
   (`Không hợp lệ`);
3. low-confidence, fuzzy, or ordinary review verdict -> `review`;
4. otherwise -> `match` (`Hợp lệ`).

This ordering avoids calling a mixed packet invalid for missing documents that
may belong to neighboring packets; its grouping must be resolved first.

### Stage 2 proposal rules

Create candidate starts from:

- high visual-cover score;
- a contract title detected in the top portion of a page;
- a participant identity different from the prior candidate's identity;
- a page gap compatible with the batch's median packet length.

A high-confidence candidate requires a contract-title signal plus either an
identity-change or cadence signal. A visual signal alone is never sufficient
to rewrite a boundary. Deduplicate candidates on the same page and sort them.

When a roster count exists, the proposal compares the candidate count to that
count. It may rank alternative candidates but must not invent or force enough
boundaries merely to equal the roster.

### Extraction gate

For newly processed or explicitly reprocessed cases:

1. detect and rank candidate starts;
2. build candidate page ranges without mutating the source upload;
3. require one consistent participant identity in each candidate range;
4. send ambiguous ranges to boundary review before field comparison;
5. run participant-level extraction only for resolved ranges;
6. persist the extractor version and evidence provenance with the revision.

Legacy manifests remain readable, but an unresolved legacy boundary assessment
prevents their mixed sources from being interpreted as participant-level truth.

## User experience

### Tổng hợp list

- `Kết quả AI`: amber `Cần review` for unresolved boundary assessments.
- `Kết quả kiểm tra`: show `Nghi ngờ nhiều hồ sơ trong một gói` for strong
  signals. Retain `Số trang bất thường`, `Cần xác nhận ranh giới`, or
  `Ranh giới gần ngưỡng` as secondary detail.
- Attention-first sorting includes these packets.
- `Cần gửi lại` counts remain based on participant evidence/rejection only;
  boundary anomalies do not increase that count.

### Packet reviewer

Display a non-dismissible amber banner under the review header:

> **Nghi ngờ nhiều hồ sơ trong một gói**  
> AI phát hiện ranh giới hoặc danh tính không nhất quán. Hãy kiểm tra và xác
> nhận ranh giới trước khi kết luận hồ sơ.

The CCCD match badge remains visible but is subordinate evidence; the banner
makes clear that matching one identity does not validate the packet.

### Boundary review screen

The case-level boundary action opens an exception-first screen containing only
affected ranges. Each range shows:

- neighboring page thumbnails;
- current boundary and proposed contract starts;
- one-based page numbers;
- non-PII signal labels;
- controls to add/remove a proposed start within the affected range.

Actions:

- `Tạo phiên bản đã sửa`: validate starts, create a new case revision, then
  navigate to it;
- `Giữ ranh giới hiện tại`: record an explicit reviewer resolution and retain
  the current case; affected packets show `Ranh giới đã xác nhận` and return to
  ordinary document/field validity evaluation;
- `Quay lại`: make no change.

After `Tạo phiên bản đã sửa`, only the affected ranges need OCR reprocessing.
Unaffected source pages may reuse immutable rendered-page assets, but field
observations and review decisions are not copied across changed boundaries.

## API behavior

Add two endpoints:

```text
GET  /api/cases/{cid}/boundary-proposal
POST /api/cases/{cid}/boundary-proposal/resolve
```

The resolve request is one of:

```json
{"action":"keep-current"}
```

or:

```json
{"action":"create-revision","starts":[7,15,23]}
```

Validation requires sorted unique integer starts within the source PDF, no
empty packet ranges, and no start in the preamble. Invalid requests return 422
without modifying either case.

`create-revision` copies the source inputs into a new case directory, records
`sourceCaseId`, and runs the existing downstream OCR/match pipeline using the
confirmed bounds. It never changes the source case. If processing fails, the
new revision is an ordinary error case and the source remains usable.

## Preservation and recovery

- Original `input.pdf`, roster, CCCD workbook, manifests, and reviews remain
  untouched.
- A corrected revision starts with empty packet reviews because evidence ranges
  changed.
- The source and corrected revision link to each other for traceability.
- Deleting a revision does not delete its source. Deleting a source does not
  cascade to revisions; revision metadata retains the source ID even if that
  source is later removed.
- Processing interruption follows the existing stale-processing recovery.

## Testing

### Pure backend tests

- a 16-page packet with an internal contract start requires review;
- repeated contract starts set `suspectedMultiplePackets`;
- a single legitimate contract and normal length remains clear;
- batch count mismatch flags only associated anomalous packets;
- candidate fusion accepts title plus identity/cadence and rejects visual-only;
- resolution validation rejects duplicates, unsorted starts, out-of-range starts,
  and empty ranges;
- creating a revision leaves source files and reviews byte-for-byte unchanged.
- a range containing two participant identities never reaches field comparison;
- a higher-confidence candidate cannot override an identity conflict;
- corrected ranges expose only observations assigned to their participant;
- `oneCellAnchor` geometry preserves its declared extent rather than inventing
  a one-cell rectangle.

### API tests

- legacy cases receive a response-only `boundaryAssessment`;
- proposal endpoints return 404 for unknown cases and 422 for invalid starts;
- keep-current persists reviewer resolution;
- create-revision returns a new case ID and preserves the source case.

### Frontend tests

- boundary review overrides an otherwise valid AI result to `Cần review`;
- `Hợp lệ` never appears for an unresolved boundary assessment;
- boundary anomalies affect attention counts but not `Cần gửi lại` counts;
- accepted-current boundaries show `Ranh giới đã xác nhận` and restore ordinary
  AI-result evaluation;
- list and packet-review warnings use the approved Vietnamese copy;
- attention-first sorting prioritizes the affected packet;
- boundary screen renders only affected ranges and sends one-based display/
  zero-based API values correctly;
- failed resolution leaves the current screen and case unchanged.

### Live verification

On a sanitized or local-only affected batch, verify that abnormal packets are
visible before opening them, no PII appears in logs, the proposed starts align
with contract title pages, and creating a revision does not change the source
case's files or review state.

## Accuracy measurement

Maintain a versioned, anonymized gold dataset containing:

- the earlier stable 32-packet batch shape;
- the failing 41-roster-row heterogeneous batch shape;
- mixed-person ranges, missing covers, repeated contract titles, rotated pages,
  missing documents, unreadable values, and CCCD images on multiple sheets;
- reviewer-confirmed packet boundaries, roster assignments, critical field
  values, and evidence locations.

Every extractor version reports:

- packet-boundary precision, recall, and exact batch accuracy;
- cross-person contamination count;
- exact critical-field accuracy by field;
- complete-packet accuracy;
- evidence-location accuracy;
- false-clear rate;
- abstention/manual-review rate;
- CCCD automatic-attachment precision;
- median reviewer time and correction count per packet.

Pilot release gates are:

1. zero cross-person contamination in the gold dataset;
2. zero false-clear packets;
3. every displayed value has navigable evidence and an extractor version;
4. every unresolved boundary produces `review` or `cannot_assess`;
5. CCCD auto-attachment has no known wrong-person attachment;
6. reviewer time improves over the current workflow on the same evaluation
   set.

Boundary and field-accuracy targets beyond the zero-error safety gates are set
only after the gold dataset size and class distribution are fixed; the design
does not invent statistically unsupported percentages.

## Rollout

1. Keep Stage 1 enabled for existing and future cases.
2. Run Stage 2 proposal generation in shadow mode and compare proposals with
   reviewer-confirmed boundaries.
3. Enable `Tạo phiên bản đã sửa` only after false boundary proposals are within
   the agreed pilot tolerance.
4. Enable Stage 3 identity-isolated comparison only for resolved revisions;
   keep legacy mixed manifests review-only.
5. Qualify Stage 4 CCCD geometry and extractor-version metrics on the gold
   dataset before enabling automatic attachment for new workbook shapes.
6. Keep all boundary rewrites reviewer-confirmed; there is no unattended auto-
   split stage in this design.

## Success criteria

- No packet with unresolved boundary evidence is shown as `Hợp lệ`.
- No unresolved-boundary packet can be published as a prepared package.
- The affected batch exposes all stored length anomalies before packet review.
- A reviewer can understand why a packet is suspicious without opening every
  document tab.
- Confirmed correction produces a separate case revision with traceable source
  linkage and no review-state leakage.
- Packet count and participant identity accuracy are measured against reviewer-
  confirmed boundaries, not inferred from one successful CCCD match.
- No field comparison combines observations from two participant identities.
- Existing cases remain reproducible because results record their extractor
  version and corrected boundaries create a new revision.
- Accuracy reporting includes false-clear and reviewer-time outcomes, not only
  OCR engine confidence.
