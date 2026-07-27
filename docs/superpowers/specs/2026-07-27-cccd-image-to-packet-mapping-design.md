# CCCD Image-to-Packet Mapping Design

**Date:** 2026-07-27  
**Target:** `main` checklist architecture (`d902b1e` or later)  
**Status:** Draft for user review

## Goal

Allow the reviewer to upload an Excel workbook containing embedded CCCD
images together with the packet PDF and roster. The app extracts and reads the
images locally, maps only high-confidence exact identities automatically, and
attaches confirmed CCCD images to the correct packet as evidence.

The OCR is an evidence-routing aid. It does not approve, reject, flag, or
otherwise decide the A1 or G-DOC checks. The reviewer keeps the verdict.

## Confirmed Product Decisions

1. **Evidence and routing:** OCR the CCCD only to route it and create focused
   evidence. The human evaluates the check.
2. **Single-pass ingest:** PDF, roster, and optional CCCD workbook are supplied
   when creating the case.
3. **In-app exceptions:** exact matches attach automatically; everything else
   remains in a case-level `Cần gán` queue.
4. **Both sides when safe:** attach front and back when they can be paired
   confidently; front-only is allowed. The back is additional evidence, not a
   requirement for automatic placement.
5. **Checklist integration:** the confirmed front image feeds A1 evidence and
   focus; presence/absence feeds G-DOC.
6. **Conservative placement:** only a high-confidence, unique, exact 12-digit
   roster-backed CCCD match may attach automatically.
7. **Manual confirmation:** fuzzy CCCD, 9-digit CMND, name-only, packet-OCR
   matches without a roster, unreadable values, and conflicts never attach
   automatically.
8. **Local PII:** images and OCR stay on the local backend. Real CCCD data is
   never committed or used in automated fixtures.
9. **Spike gate:** a measured go/no-go spike must pass before persistence, API,
   checklist, or frontend implementation starts.

## Current Architecture

The target is the current `main` branch:

- backend API on port 8000;
- `server/pipeline.py` returns `{"summary", "packets"}`;
- `server/app.py::_run_case` gives that result to
  `CaseStore.set_result`;
- `CaseStore` exclusively owns `case.json`;
- packet manifests contain `docs`, `fields`, and derived `checks`;
- reviewer state is `review.items`, keyed by checklist code;
- A1 and G-DOC are built by `server/checklist.py`;
- `id_front` and `id_back` already exist in `EvidenceKind`; and
- A1 is currently routed to the contract CCCD source.

This feature extends those contracts. It does not restore the older
field-keyed reviewer architecture.

## Phase 0: Mandatory Go/No-Go Spike

### Purpose

Measure whether the actual CCCD workbook layout and OCR quality support a
useful exact-only workflow before building durable storage and UI.

### Inputs

- the supplied CCCD workbook;
- its corresponding roster; and
- local reviewer ground truth for a manual audit.

The supplied workbook alone can measure extraction, side classification,
pairing, region location, and OCR. A final routing go/no-go decision requires
the corresponding roster.

### Spike Scope

The spike implements only:

1. OOXML drawing extraction;
2. image decoding and orientation;
3. front/back/unknown classification;
4. conservative front/back pairing;
5. CCCD-number region location;
6. region-only digit OCR;
7. name OCR for manual suggestions;
8. duplicate-aware exact roster matching; and
9. a local, masked metrics report.

It does not change:

- `case.json`;
- packet manifests;
- the production API;
- checklist behavior;
- frontend screens; or
- existing cases.

No real image, OCR transcript, identity, roster row, contact sheet, or result
file may be committed. Temporary spike output must remain outside the repo or
under already ignored local data paths.

### Region Location Is Required

The automatic-match number must come from a located identity-number region:

1. find a CCCD-number label such as `Số`, `No.`, or
   `Số định danh cá nhân`;
2. derive the adjacent or next-line number region;
3. crop that region;
4. run digit-whitelisted OCR only inside the crop; and
5. retain the crop bounding box for later A1 focus.

Whole-image numeric OCR may assist diagnostics but can never supply an
automatic-placement number. If no usable number region is found, the image
stays manual.

### Metrics

Measure separately:

- supported drawing extraction rate;
- front/back/unknown classification;
- pair coverage and pair correctness;
- number-region location rate;
- exact 12-digit read rate;
- exact unique roster auto-placement rate;
- unique name-suggestion rate;
- fully unassigned/manual-search rate;
- false pair count; and
- false automatic-attachment count.

All proposed automatic pairs and attachments are manually audited during the
spike.

Placement coverage uses one fixed denominator:

`expected mappable packets` = processed packets linked to one unique roster row
whose roster CCCD contains exactly 12 digits.

An absent card, failed extraction, unreadable number, or unresolved mapping
therefore lowers coverage rather than disappearing from the metric.

### Go/No-Go Thresholds

Proceed to the full build only when one spike run demonstrates:

- 100% extraction of supported PNG/JPEG drawing instances;
- zero incorrect automatic front/back pairs;
- zero incorrect automatic packet attachments;
- at least 85% exact automatic packet placement;
- at least 95% covered by exact automatic placement plus unique one-click
  name suggestions; and
- no more than 5% requiring packet search/manual assignment.

One focused region/OCR tuning iteration is allowed if the exact placement rate
is below 85%. If the rerun still misses any threshold, stop the feature build
and reconsider the input format or require a structured card index. Do not
lower the exact-match safety rule to improve coverage.

## Full-Build Scope

The following sections apply only after the spike passes.

### Included

- Optional CCCD `.xlsx` input on case creation.
- OOXML drawing and relationship traversal.
- PNG/JPEG extraction and local OCR.
- Conservative front/back pairing.
- Exact CCCD automatic attachment.
- Name-only suggestions requiring confirmation.
- Durable mapping records for attached and unresolved candidates.
- Case-level mapping summary and `Cần gán` panel.
- Confirm, assign, reassign, replace, and detach actions.
- Front/back evidence tabs in the existing viewer.
- A1 evidence/focus integration.
- G-DOC card-presence hint.
- Restart-safe persistence and idempotent manifest updates.

### Not Included

- CCCD authenticity, tampering, expiry, liveness, or face verification.
- QR validation or government-service lookup.
- Automatic reviewer verdicts or flags.
- Automatic attachment based on workbook position, image order, name, fuzzy
  digits, 9-digit CMND, or packet order.
- Uploading or replacing a CCCD workbook after case creation.
- Backfilling existing cases.
- Bulk CCCD export.
- External/cloud OCR.
- Changes to the meaning of A1, G-DOC, reviewer completion, case progress, or
  report inclusion.

## User Flow

### Upload

The case upload screen adds a third input:

1. packet PDF — required;
2. roster Excel — optional in the existing app; and
3. CCCD image Excel — optional `.xlsx`.

Automatic placement requires a roster. A CCCD workbook without a roster is
allowed, but all candidates remain suggestions/manual assignments.

The upload request remains one case-creation operation. A new progress stage is
shown after packet OCR:

`cccd` → `Đọc và ghép ảnh CCCD…`

Individual image failures do not fail the packet case. The CCCD result becomes
`partial`, with unresolved candidates kept for the reviewer.

### Case Detail

When a CCCD workbook was supplied, show:

`CCCD: <attached>/<candidate sets> đã gắn · <suggested> cần xác nhận · <unmatched> cần gán`

`Xử lý CCCD` opens the mapping panel whenever candidates need confirmation,
manual assignment, conflict resolution, or side replacement.

Each candidate row shows:

- front/back thumbnails when available;
- side classification;
- OCR name;
- masked CCCD (`********1234`);
- mapping state and issue;
- suggested packet; and
- match method.

Actions:

- `Xác nhận` — accept a unique name suggestion;
- `Chọn gói` — manually select a packet;
- `Gán lại` — move an attached mapping;
- `Thay thế` — explicitly replace an occupied front/back side; and
- `Gỡ khỏi gói` — detach while preserving the candidate.

One candidate can be attached to at most one packet. A packet can have at most
one external front image and one external back image. A paired candidate
occupies both slots; separate front-only/back-only candidates may occupy one
slot each.

### Packet Review

Confirmed mappings add:

- `CCCD (Excel) · Mặt trước`
- `CCCD (Excel) · Mặt sau`, when safely paired or manually assigned

The existing viewer handles tabs, zoom, scroll, focus, and roster callout.

Selecting A1 opens the confirmed `id_front` document at the located CCCD
number box. The OCR value is presented as source evidence, while A1 remains a
human-reviewed checklist item.

G-DOC shows a system hint when a CCCD workbook was supplied but no confirmed
front image is present:

`Thiếu CCCD`

The hint does not create a reviewer flag or mark G-DOC failed. The reviewer
decides whether to flag G-DOC.

The back is extra evidence. A front-only mapping is not automatically treated
as missing CCCD.

## Extraction and OCR

### OOXML Traversal

Create `server/cccd_ingest.py` with a pure extraction boundary:

```python
extract_drawings(xlsx_path: str, output_dir: str) -> list[EmbeddedDrawing]
```

For every worksheet:

1. resolve its drawing relationship;
2. parse every supported two-cell/one-cell drawing anchor;
3. resolve the embedded media relationship;
4. validate and decode the image;
5. assign a server-owned ID and filename; and
6. preserve sheet and anchor geometry.

Do not assume:

- a single worksheet;
- `drawing1.xml`;
- media filename order;
- left/right columns;
- one drawing per media file; or
- populated worksheet cells.

Create one record per drawing instance, even when two drawings reference the
same bytes.

Accepted media:

- PNG;
- JPEG.

Side classification returns `front`, `back`, or `unknown`. Unknown images are
preserved for manual handling.

### Conservative Pairing

A front/back pair is eligible only when:

- both images are on the same worksheet;
- their vertical anchor intervals overlap by at least 50%, or their start rows
  differ by at most one;
- they classify as opposite known sides; and
- neither is already assigned.

Among eligible images, accept only mutual nearest neighbors by anchor-center
distance. When another eligible candidate exists, the selected distance must
be at least 20% smaller than the next alternative on both sides. Otherwise,
keep the images separate.

Anchor position can pair sides. It can never identify the owner.

### OCR Output

```python
CccdImageOcr(
    side: Literal["front", "back", "unknown"],
    side_confidence: float,
    cccd: str,
    cccd_confidence: float,
    name: str,
    name_confidence: float,
    number_bbox: Bbox | None,
)
```

The backend stores only the mapping fields and source box, not the full raw OCR
transcript.

## Matching Rules

Use a duplicate-aware CCCD roster index:

```python
dict[str, list[RosterRow]]
```

Do not reuse the existing first-row-wins `by_cccd` dictionary for the
automatic-placement decision, because it cannot detect duplicate roster
identifiers.

### Automatic

Attach automatically only when:

1. the located region produced exactly 12 digits;
2. number confidence is at least `0.85`;
3. the digits match exactly one roster row;
4. exactly one processed packet is linked to that roster identity;
5. no competing candidate targets that packet side; and
6. pairing and identity contain no conflict.

Persist `matchedBy: "cccd"`.

### Suggested

A unique normalized name can suggest one packet when:

- there is no eligible exact CCCD match;
- the name confidence is at least `0.80`;
- the name matches exactly one roster/packet identity; and
- no competing candidate targets that packet.

It never attaches until the reviewer confirms it. After confirmation persist
`matchedBy: "name"`.

An exact packet-PDF OCR match without a roster is also a manual suggestion, not
an automatic attachment.

### Manual

The following always remain manual:

- fuzzy/edit-distance CCCD;
- 9-digit CMND;
- whole-image numeric reads without a number box;
- low-confidence digits or name;
- duplicate roster identifiers or names;
- conflicting name and CCCD;
- multiple packet targets;
- unreadable identity;
- unknown-side images;
- ambiguous/unpaired backs;
- duplicate candidates; and
- roster rows without packets.

Manual selection persists `matchedBy: "manual"`.

## Pipeline and Store Boundary

Extend:

```python
run_pipeline(
    pdf_path,
    roster_path,
    job_dir,
    progress_cb,
    cccd_xlsx_path=None,
) -> {
    "summary": ...,
    "packets": ...,
    "cccdWorkbook": ...,
}
```

The pipeline may write extracted image assets and packet manifests under the
case directory, as it already writes packet assets. It must not read or write
`case.json`.

`server/app.py::_run_case` passes all three result values to:

```python
CaseStore.set_result(
    cid,
    summary=result.get("summary"),
    packets=result.get("packets", []),
    cccd_workbook=result.get("cccdWorkbook"),
)
```

`CaseStore.set_result` normalizes and persists the mappings with the packets.
Existing calls that omit `cccd_workbook` behave as before.

## Persistent Mapping Model

`case.json` gains nullable `cccdWorkbook`. Existing cases normalize a missing
property to `null`.

```json
{
  "cccdWorkbook": {
    "fileName": "CCCD.xlsx",
    "status": "ready",
    "revision": 1,
    "summary": {
      "images": 0,
      "candidateSets": 0,
      "attached": 0,
      "suggested": 0,
      "unmatched": 0,
      "conflicts": 0
    },
    "mappings": [
      {
        "id": "cccd-001",
        "images": [
          {
            "id": "drawing-001",
            "side": "front",
            "path": "cards/cccd-001-front.png",
            "width": 1059,
            "height": 668,
            "sha256": "<hex>",
            "anchor": {
              "sheet": "CCCD",
              "fromRow": 1,
              "fromCol": 0,
              "toRow": 10,
              "toCol": 1
            }
          }
        ],
        "ocrIdentity": {
          "cccd": "<12 digits or empty>",
          "name": "<normalized display name or empty>",
          "cccdConfidence": 0.0,
          "nameConfidence": 0.0,
          "numberBbox": null
        },
        "state": "suggested",
        "suggestedPacketIndex": 0,
        "attachedPacketIndex": null,
        "matchedBy": null,
        "issues": ["name-only"]
      }
    ]
  }
}
```

Workbook status:

- `processing`
- `ready`
- `partial`
- `error`

Mapping state:

- `attached`
- `suggested`
- `unmatched`
- `conflict`

Match method:

- `cccd`
- `name`
- `manual`
- `null`

Attached candidates remain in `mappings`; assignment never deletes
provenance. Summary counters are recomputed from mappings before every write.
`revision` begins at 1 and increments after every successful manual mutation.

## Manifest and Checklist Integration

### Mapping-Owned Evidence

Use stable document IDs:

- `cccd-excel-<mapping-id>-front`
- `cccd-excel-<mapping-id>-back`

Confirmed attachment:

1. copies server-owned image assets into the packet directory;
2. appends one-page `id_front`/`id_back` documents;
3. appends the located CCCD source to the existing `cccd` field;
4. rebuilds manifest checks;
5. writes the manifest atomically; and
6. updates the persisted mapping state.

Detach/reassign removes only docs and sources whose IDs use that mapping's
prefix, then rebuilds checks on every affected packet. Reapplying the same
mapping is idempotent.

Existing PDF evidence is never removed or replaced. If multiple `id_front`
documents exist, A1 prefers a confirmed `cccd-excel-*` front, then another
`id_front`, then its current contract fallback.

### A1

Modify `build_checklist` so A1:

- routes to the preferred `id_front` source when present;
- retains the roster CCCD as `reference`;
- uses the located CCCD value/bbox as `source`;
- sets `evidenceDocId` to the mapped front document; and
- keeps `autostatus: "review"` for the mapped Excel card so OCR does not
  become the human verdict.

When no confirmed front exists, A1 retains its current contract behavior.

### G-DOC

When a CCCD workbook was supplied, the manifest records:

```json
{ "cccdEvidenceExpected": true }
```

Extend the pure builder compatibly:

```python
build_checklist(fields, match, docs, *, cccd_expected=False)
```

The pipeline and every mapping-driven checklist rebuild pass the manifest's
`cccdEvidenceExpected` value. `build_checklist` derives card presence from
confirmed `id_front` docs:

- front present → no CCCD hint;
- no front → optional check attention `missing-cccd`.

Extend `CheckItem` additively:

```ts
type CheckAttention = "missing-cccd"

interface CheckItem {
  // existing fields unchanged
  attention?: CheckAttention
}
```

G-DOC displays `Thiếu CCCD` when attention is present. Attention never writes
`review.items["G-DOC"].flag`; the reviewer chooses whether to flag it.

Existing manifests without the workbook-expected marker keep current G-DOC
behavior.

The existing lazy checklist rebuild in `GET .../manifest.json` must also pass
the marker. Its default remains false for legacy manifests.

## Manual Mapping Mutations

Create a case-scoped mapping service that serializes mutations with a per-case
lock.

```http
GET /api/cases/{caseId}/cccd-mappings
```

Returns revision, summary, masked list metadata, image URLs, suggestions, and
packet targets.

```http
PUT /api/cases/{caseId}/cccd-mappings/{mappingId}
Content-Type: application/json

{
  "packetIndex": 12,
  "expectedRevision": 4,
  "replaceOccupiedSide": false
}
```

`packetIndex: null` detaches.

Rules:

- validate case, mapping, packet, and image side;
- reject stale revision with HTTP 409;
- reject occupied sides with HTTP 409 and conflict metadata;
- require `replaceOccupiedSide: true` for replacement;
- stage and validate affected manifests plus case JSON;
- atomically replace each destination under the case lock;
- retain backups until all replacements succeed and restore them on failure;
  and
- return the new revision, summary, mappings, and affected packet metadata.

Images are served only through IDs resolved from mapping metadata:

```http
GET /api/cases/{caseId}/cccd-mappings/{mappingId}/images/{imageId}
```

Clients never supply a filesystem path.

## API Changes

Extend case creation:

```http
POST /api/cases
pdf=<required PDF>
roster=<optional XLSX>
cccd=<optional XLSX>
```

The response remains `{ "case_id": "..." }`.

`GET /api/cases/{caseId}` adds only a compact CCCD summary. It does not inline
mapping records or image data.

There is no post-creation upload endpoint in this scope.

## Error Handling

- Invalid workbook/no supported drawings: keep the packet case usable and set
  CCCD status `error`.
- Individual image failure: preserve remaining candidates and set `partial`.
- OCR failure: keep the image as `unmatched`.
- Ambiguous pairing: keep images separate.
- Identity conflict: attach nothing.
- Missing roster: create manual suggestions only.
- Manifest/mapping mutation failure: expose no false attachment state.
- Stale mapping UI: HTTP 409, refresh, preserve the user's pending selection.
- Interrupted initial processing: use the existing interrupted-case behavior;
  no partially written mapping is considered confirmed.

## Privacy and Security

- Process entirely on the local backend.
- Never send CCCD images/OCR to GreenNode or another external service.
- Never log full names, CCCD numbers, raw OCR text, image bytes, or workbook
  contents.
- Mask CCCD in list-level UI and routine errors.
- Store source workbook and images only in the ignored case directory.
- Case deletion removes workbook, extracted images, packet copies, thumbnails,
  and mapping metadata.
- Use synthetic PII-free fixtures only.
- Reject path traversal, encrypted archives, external relationships,
  unsupported media, and malformed drawing relationships.
- Limit workbook size to 100 MB, drawing instances to 500, embedded images to
  25 MB each, accepted uncompressed image bytes to 500 MB total, and decoded
  images to 40 megapixels each.
- Decode every accepted image with Pillow; extension and content type are not
  trusted.

## Compatibility

- Existing clients omitting `cccd` are unchanged.
- Existing cases normalize `cccdWorkbook` to null.
- Existing manifests without the CCCD-expected marker retain current A1 and
  G-DOC behavior.
- Existing `review.items`, completion, case progress, reports, recap, and
  packet matching are unchanged.
- No existing PDF evidence is removed.
- No post-creation backfill is promised.

## Testing

### Spike

- Run locally on the real workbook and corresponding roster.
- Manually audit every proposed pair and automatic attachment.
- Record only aggregate/masked metrics.
- Enforce the go/no-go thresholds exactly.

### Pure backend

- Traverse multiple sheets/drawings through relationships.
- Preserve drawing order independent of media filename order.
- Reject traversal, external relationships, malformed archives, invalid media,
  decompression limits, and pixel limits.
- Classify front/back/unknown.
- Locate number region; no region means no automatic CCCD.
- Pair valid neighbors; reject competing/ambiguous pairs.
- Detect duplicate roster CCCD/name entries.
- Exact 12-digit unique match attaches.
- Fuzzy, CMND, name-only, no-roster, low-confidence, conflicting, duplicate,
  unreadable, and unpaired cases stay manual/suggested.
- Mapping summaries and revisions.
- Manifest injection, A1 preference, G-DOC attention, idempotency, cleanup,
  detach, reassign, and replacement.

### Store and API

- Pipeline returns `cccdWorkbook`; `set_result` persists it.
- Pipeline never writes `case.json`.
- Existing cases migrate to null.
- Restart preserves attached and unresolved mappings.
- Mapping list masks CCCD.
- Confirm, manual assign, detach, reassign, occupied-side replacement,
  stale-revision, invalid packet, and not-found responses.
- Failed mutation produces no partial state.
- Image endpoint cannot escape the case directory.
- Case deletion removes every CCCD artifact.

### Frontend

- Third upload input and request payload.
- CCCD progress label.
- Case summary and `Cần gán` panel states.
- Masked candidate list and authorized image preview.
- Explicit confirmation for every non-exact match.
- Assign/reassign/replace/detach, loading, error, and 409 refresh.
- A1 opens front image at the number box.
- G-DOC missing hint does not create a reviewer flag.
- Front-only evidence works; back remains optional.

### End-to-End

Use a generated synthetic workbook containing:

- exact front/back pair;
- exact front-only card;
- unique name-only suggestion;
- unreadable/unmatched image;
- duplicate roster identifier;
- ambiguous pair;
- media filenames out of drawing order; and
- one invalid image.

Verify persistence through reload/backend restart, checklist focus, manual
mapping, replacement, cleanup, no report/completion regression, full test
suites, production build, and browser console.

No real CCCD image or identity may enter tests, snapshots, docs, or QA
artifacts.

## Acceptance Criteria

### Spike

1. The corresponding roster is available.
2. Supported drawings extract completely.
3. Manual audit finds zero false pairs and zero false automatic attachments.
4. Exact auto-placement is at least 85%.
5. Auto-placement plus one-click suggestions is at least 95%.
6. Manual packet search is no more than 5%.
7. All thresholds pass before the full build begins.

### Full Build

1. The user can submit PDF, roster, and CCCD workbook in one case creation.
2. Only a high-confidence exact 12-digit unique roster match auto-attaches.
3. All other matches require human confirmation or assignment.
4. Every candidate remains durably represented after attachment.
5. Confirmed images appear as packet evidence.
6. A1 focuses the mapped front number region without creating a verdict.
7. G-DOC surfaces missing card evidence without automatically flagging.
8. Attach, detach, reassign, and replacement are persistent, conflict-safe,
   and idempotent.
9. Existing cases and checklist behavior remain compatible.
10. All PII remains local and is deleted with the case.
