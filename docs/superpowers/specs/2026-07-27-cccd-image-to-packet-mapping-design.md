# CTV v1 CCCD Image-to-Packet Mapping Design

**Date:** 2026-07-27  
**Status:** Draft for user review

## Goal

Allow a reviewer to upload an Excel workbook containing embedded CCCD images
alongside the packet PDF and roster, then:

1. extract the original embedded images;
2. identify CCCD front and back images;
3. OCR the identity needed for matching;
4. map each CCCD image set to the correct processed packet;
5. attach confirmed images to that packet as reviewable evidence; and
6. route every uncertain mapping to a human confirmation queue.

The feature is successful when the reviewer opens a packet and sees its mapped
CCCD front/back images in the document viewer, with supported identity fields
linked to their source regions.

This work applies only to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

The v2 checkout is out of scope. V1 continues to use frontend port 5174 and
backend port 8001.

## Product Decision

Automatic attachment requires a high-confidence, exact 12-digit CCCD match to
one roster-backed packet.

A unique name-only match is a suggestion, not an attachment. It shows
`! Cần xác nhận CCCD` on the suggested packet and requires an explicit reviewer
confirmation.

Unreadable, duplicate, conflicting, or otherwise ambiguous identities are
never guessed. They remain in the case-level manual mapping queue.

## Reference Workbook Findings

The supplied local reference `CCCD_T2.xlsx` is an image canvas:

- it has one worksheet;
- it contains 61 embedded drawing images (59 PNG and 2 JPEG);
- it has no populated worksheet cells; and
- drawing anchors provide visual position, but no person identifier.

The source workbook must remain local and untracked. Its exact image count,
layout, media names, and row positions are observations, not product
assumptions.

The extractor must follow OOXML workbook, worksheet, drawing, and relationship
files to recover each drawing instance and its anchor. It must not assume that
`xl/media/imageN.*` filename order equals worksheet order.

## Scope

### Included

- An optional third upload: CCCD image workbook (`.xlsx`).
- Embedded PNG/JPEG extraction from worksheet drawings.
- Local front/back classification and OCR.
- Conservative front/back candidate pairing.
- Exact CCCD auto-attachment.
- Name-only manual suggestions.
- A case-level mapping summary and confirmation interface.
- Manual confirm, assign, reassign, and detach.
- Packet attention reasons for missing, incomplete, or unconfirmed CCCD.
- Injection of confirmed CCCD documents and supported field sources into the
  existing packet manifest.
- Persistence and resume after browser/backend restart.
- Existing-case compatibility when no CCCD workbook is supplied.

### Not Included

- CCCD authenticity, tampering, expiry, liveness, or face verification.
- QR-code validation against a government service.
- Automatic rejection or payment eligibility decisions.
- Automatic attachment based only on a name, workbook position, image order,
  or packet order.
- Sending CCCD images or OCR text to an external AI service.
- Bulk export of CCCD images.
- Uploading/replacing a CCCD workbook after a case has already been created.
- Changes to reviewer lifecycle status, packet rejection, case reports, or
  packet completion rules.

## User Flow

### 1. Upload

The existing upload card contains three inputs:

1. packet PDF — required;
2. roster Excel — optional in the existing product, but required for automatic
   CCCD attachment; and
3. CCCD image Excel — optional, accepts `.xlsx`.

The start button continues to require only the PDF. Selecting a CCCD workbook
without a roster is allowed, but all identity matches remain suggestions that
require manual confirmation.

The upload copy explains:

> Ảnh CCCD sẽ được đọc và gắn vào đúng gói hồ sơ. Chỉ trường hợp khớp chính
> xác số CCCD với bảng kê mới được gắn tự động.

### 2. Processing

The existing pipeline finishes packet splitting, packet OCR, and roster
alignment first. It then runs a new progress stage:

`cccd` → `Đọc và ghép ảnh CCCD…`

Individual CCCD OCR/mapping failures do not fail the entire case. The case
becomes reviewable with a partial/error CCCD summary and unresolved candidates
in the manual queue.

### 3. Case Detail

When a CCCD workbook was supplied, case detail shows a compact banner:

`CCCD: <attached>/<candidate sets> đã gắn · <needs confirmation> cần xác nhận · <unmatched> chưa khớp`

The banner includes a `Xử lý CCCD` button whenever any mapping needs
confirmation, is unmatched, is incomplete, or is conflicting.

Packets use the existing orthogonal amber attention marker:

- `Cần xác nhận CCCD` — a name-only suggestion points to this packet;
- `Chưa gắn CCCD` — workbook processing completed but the packet has no
  confirmed CCCD front image;
- `Thiếu ảnh CCCD` — only one side is attached or the image set is incomplete.

These are system-attention reasons only. They never change `Chưa xem`,
`Đang xem`, `Đã xong`, or `Flagged`; never mark a packet complete; and never
add it to the send-back report.

### 4. Manual Mapping

`Xử lý CCCD` opens a mapping panel containing one candidate set per row:

- front/back thumbnails when available;
- detected side for each image;
- extracted name;
- masked CCCD (`********1234`);
- mapping state;
- suggested packet, when one exists; and
- the reason confirmation is required.

Full image and full CCCD remain available inside the authorized mapping panel
for disambiguation, but list-level copy uses masked identifiers.

Actions:

- `Xác nhận` — attach the candidate to its unique suggested packet;
- `Chọn gói khác` — search packets by name and masked CCCD, then attach;
- `Gán lại` — atomically move an attached candidate to another packet; and
- `Gỡ khỏi gói` — detach while preserving the extracted candidate for later
  remapping.

One candidate set can be attached to at most one packet. A packet can have at
most one confirmed external front image and one confirmed external back image.
A paired candidate occupies both side slots; separate front-only and back-only
candidates may occupy one slot each. Replacing an occupied side requires a
visible confirmation.

### 5. Packet Review

A confirmed candidate adds evidence tabs:

- `CCCD (Excel) · Mặt trước`
- `CCCD (Excel) · Mặt sau`, when present

Each image is a one-page `EvidenceDoc` with its natural pixel dimensions. The
front image can contribute sources for:

- `hoten`;
- `cccd`; and
- `ngaysinh`.

Only OCR hits with a non-empty value and usable bounding box become field
sources. Existing expected roster values are unchanged. CCCD evidence remains
a human-review aid; OCR does not produce a verdict.

## Processing Architecture

The work is split into five focused backend units.

### `cccd_workbook.extract_drawings`

Input: the saved `.xlsx` path.

Output:

```python
EmbeddedDrawing(
    id: str,
    sheet: str,
    anchor: Anchor,
    media_type: Literal["image/png", "image/jpeg"],
    extension: Literal["png", "jpg"],
    width: int,
    height: int,
    sha256: str,
    stored_path: str,
)
```

Implementation rules:

- use Python `zipfile` and `xml.etree.ElementTree`;
- traverse workbook/sheet/drawing relationship files;
- create one record per drawing instance, even when image bytes are repeated;
- accept PNG and JPEG only;
- generate server-owned safe filenames rather than trusting archive paths;
- reject path traversal, encrypted archives, external image relationships,
  unsupported media, and malformed drawing relationships; and
- never execute macros, formulas, links, or embedded objects.

### `cccd_workbook.ocr_drawing`

Use the existing local Pillow/pytesseract stack and rotation handling. Return
only the fields necessary for mapping and review:

```python
CccdImageOcr(
    side: Literal["front", "back", "unknown"],
    side_confidence: float,
    cccd: str,
    cccd_confidence: float,
    name: str,
    name_confidence: float,
    birth_date: str,
    birth_date_confidence: float,
    sources: dict[str, SourceHit],
)
```

Front-side signals include the CCCD heading, 12-digit identifier, name, and
date-of-birth labels. Back-side signals include the identification-features,
issue-date/authority, and card-back labels. Unknown side remains valid input to
manual mapping.

The system stores normalized extracted fields and source boxes, not the full
raw OCR transcript.

### `cccd_workbook.pair_images`

Each recognized front starts one candidate set. A back image is eligible only
when it is on the same worksheet and either:

- its vertical anchor interval overlaps the front by at least 50%; or
- its starting drawing row differs by at most one.

Eligible images are compared by anchor-center distance. A pair is accepted only
when front and back are mutual nearest neighbors and the selected distance is
at least 20% smaller than the next eligible alternative on both sides. There
must be no competing front/back assignment.

Workbook anchor position is a pairing hint only. It cannot establish owner
identity.

The pairing result can be:

- front + back;
- front only;
- back only; or
- ambiguous images kept separate for manual handling.

The function is deterministic, one-to-one, and never merges two recognized
fronts. An uncertain pair remains incomplete rather than being guessed.

### `cccd_matching.resolve_candidates`

Matching operates after processed packets and their roster identities exist.

#### Automatic attachment

Attach automatically only when all conditions hold:

1. OCR produced exactly 12 digits;
2. CCCD OCR confidence is at least `0.85`;
3. the number matches exactly one roster CCCD after stripping separators;
4. exactly one processed packet is linked to that roster identity;
5. no other CCCD candidate is attached or auto-matched to that packet; and
6. the candidate has no pairing/identity conflict.

The persisted method is `cccd`.

#### Name suggestion

Create a suggestion, without attachment, only when:

1. the normalized OCR name is non-empty;
2. it matches exactly one processed packet/roster name;
3. no exact CCCD match exists;
4. no duplicate candidate targets the same packet; and
5. name OCR confidence is at least `0.80`.

The persisted method is `name` only after a reviewer confirms it.

#### Manual queue

All other results become `unmatched` or `conflict`, including:

- unreadable CCCD and name;
- low-confidence identity;
- duplicate names;
- duplicate CCCD candidates;
- conflicting name and CCCD;
- multiple possible packets;
- back-only images;
- ambiguous front/back pairs; and
- cases with no roster-backed exact target.

Exact CCCD read from the packet PDF can be shown as an additional manual
suggestion when no roster exists, but it does not qualify for automatic
attachment.

### `cccd_manifest.apply_mapping`

Confirmed attachment is an idempotent manifest operation:

1. remove any prior documents and sources owned by this mapping;
2. remove this mapping from any previous packet during reassignment;
3. copy the server-owned image assets into the target packet directory using
   safe mapping-derived names;
4. append front/back `EvidenceDoc` records;
5. append supported OCR field sources using mapping-owned document IDs;
6. write the manifest atomically; and
7. update mapping/packet attention state in the same store transaction.

Document IDs are stable:

- `cccd-excel-<mapping-id>-front`
- `cccd-excel-<mapping-id>-back`

The prefix makes detach/reassign cleanup precise without adding provenance
fields to the existing manifest schema.

If the packet already contains CCCD evidence from the PDF, the Excel images
are still added with their explicit `(Excel)` labels. Existing evidence is
never replaced or silently removed.

## Persistent Data Model

`case.json` gains an additive nullable `cccdWorkbook` object. Existing cases
normalize a missing property to `null`.

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
      "needsConfirmation": 0,
      "unmatched": 0,
      "incomplete": 0
    },
    "mappings": [
      {
        "id": "cccd-001",
        "images": [
          {
            "id": "drawing-001",
            "side": "front",
            "path": "cccd/cccd-001/front.png",
            "width": 1000,
            "height": 630,
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
          "cccd": "<normalized digits>",
          "name": "<normalized display text>",
          "birthDate": "<normalized date>",
          "cccdConfidence": 0.0,
          "nameConfidence": 0.0
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

Allowed workbook status values:

- `processing`
- `ready`
- `partial`
- `error`

Allowed mapping states:

- `attached`
- `suggested`
- `unmatched`
- `conflict`

Allowed `matchedBy` values:

- `cccd`
- `name`
- `manual`
- `null`

All summary values are recomputed from mappings before every write rather than
trusted from request bodies. `revision` starts at `1` when extraction results
are persisted and increments after every successful manual mapping mutation.

## API Contract

### Create case

Extend the existing multipart request:

```http
POST /api/cases
pdf=<required PDF>
roster=<optional XLSX>
cccd=<optional XLSX>
```

The response remains:

```json
{ "case_id": "<id>" }
```

### Case detail

`GET /api/cases/{caseId}` adds a compact `cccdMapping` summary and packet-level
CCCD attention flags. It does not inline images or the complete mapping list.

### Mapping list

```http
GET /api/cases/{caseId}/cccd-mappings
```

Returns mapping metadata, candidate thumbnails/asset URLs, masked identity for
the list, and the available packet targets.

### Mapping mutation

```http
PUT /api/cases/{caseId}/cccd-mappings/{mappingId}
Content-Type: application/json

{
  "packetIndex": 12,
  "expectedRevision": 4,
  "replaceOccupiedSide": false
}
```

A numeric packet index confirms, attaches, or reassigns. A null packet index
detaches:

```json
{ "packetIndex": null, "expectedRevision": 4 }
```

The server validates that case, mapping, and packet exist and that a candidate
does not occupy an already-filled packet side without explicit replacement
confirmation. When a side is occupied it returns HTTP 409 with the conflicting
mapping; the reviewer may confirm replacement and retry with
`replaceOccupiedSide: true`. `cccdWorkbook.revision` increments after each
successful mapping mutation. A mismatched `expectedRevision` also returns HTTP
409. The response includes the new revision, updated mapping summary, and
affected packet metadata.

### Mapping image

```http
GET /api/cases/{caseId}/cccd-mappings/{mappingId}/images/{imageId}
```

The server resolves the image ID from persisted mapping metadata; clients
cannot pass a filesystem path.

## Attention Integration

Add these known pipeline flags and labels to the existing dashboard helper:

| Packet flag | Attention copy |
| --- | --- |
| `cccd-needs-confirmation` | `Cần xác nhận CCCD` |
| `cccd-missing` | `Chưa gắn CCCD` |
| `cccd-incomplete` | `Thiếu ảnh CCCD` |

`cccd-missing` is computed only when a CCCD workbook was supplied and
processing reached `ready` or `partial`.

Attention flags are recomputed after initial matching and every manual mapping
mutation:

- confirmed front and back clear `cccd-missing` and `cccd-incomplete`;
- no confirmed front adds `cccd-missing`;
- exactly one confirmed side adds `cccd-incomplete`;
- any unconfirmed name suggestion adds `cccd-needs-confirmation`; and
- the confirmation flag clears only when no pending suggestion points to that
  packet.

Unmatched case-level candidates do not invent a packet association. They are
represented by the case banner and mapping queue only.

## Error Handling

- Invalid workbook or no supported drawings: keep the processed case usable;
  set CCCD workbook status to `error` and show a retry-by-new-case message.
- Individual corrupt/unsupported image: record an issue and continue.
- OCR failure: preserve the image as an unmatched manual candidate.
- Ambiguous pairing: preserve separate candidates; do not guess.
- Matching conflict: attach nothing; show both signals in the manual panel.
- Manifest update failure: perform no mapping-state change and return a
  retryable error.
- Mapping mutation conflict from a stale screen: return HTTP 409 and refresh
  the mapping panel.
- Backend restart during processing: use the existing interrupted-case
  behavior; no partially written manifest is treated as confirmed.

## Privacy and Security

- Process entirely on the local v1 backend.
- Never transmit CCCD images or OCR text externally.
- Never log names, full CCCD numbers, raw OCR text, workbook contents, or image
  bytes.
- Mask CCCD in list-level UI and routine error messages.
- Store the original workbook and extracted assets only inside the case
  directory, which is already gitignored.
- Case deletion removes the source workbook, extracted candidates, attached
  copies, mapping metadata, and thumbnails.
- Tests and documentation use synthetic identities and generated placeholder
  images only.
- Do not commit the supplied workbook, extracted images, case JSON, manifests,
  screenshots, or OCR output.
- Limit the CCCD workbook to 100 MB, 500 drawing instances, 25 MB per embedded
  image, and 500 MB total uncompressed accepted image bytes. Reject the
  workbook before extraction when a limit is exceeded.
- Decode every accepted image with Pillow and reject images above 40
  megapixels before OCR; file extensions alone are not trusted.

## Compatibility

- Existing `POST /api/cases` clients that omit `cccd` continue unchanged.
- Existing cases normalize `cccdWorkbook` to `null`.
- Existing `PacketReview`, packet lifecycle, rejection, progress, reports,
  roster matching, and manifest fields remain compatible.
- `id_front` and `id_back` are already valid evidence kinds.
- Missing CCCD workbook data produces no CCCD attention flags.
- The v2 checkout and port 8000 data remain untouched.

## Testing Strategy

### Pure backend tests

- OOXML drawing/relationship traversal uses worksheet order, not media
  filenames.
- PNG/JPEG extraction, safe filenames, metadata, hashes, and limits.
- Rejection of traversal, external relationships, malformed drawings,
  unsupported media, decompression limits, and excessive pixel count.
- Front/back/unknown classification on synthetic OCR words.
- Deterministic pairing: valid pair, front-only, back-only, competing images,
  and ambiguous layout.
- Exact 12-digit unique roster match auto-attaches.
- Low-confidence exact number does not auto-attach.
- Unique name creates a suggestion only.
- Duplicate name, duplicate CCCD, conflicting identity, no roster, and
  unreadable identity stay manual.
- Summary recomputation and attention-flag recomputation.
- Manifest injection is idempotent.
- Attach, detach, and reassign remove only mapping-owned docs/sources.
- Existing PDF evidence and expected values remain unchanged.

### Store and API tests

- Legacy cases normalize `cccdWorkbook` to null.
- Optional multipart CCCD upload is persisted inside the case directory.
- Processing can complete as partial when individual images fail.
- Case detail exposes compact summary without image data.
- Mapping list masks list-level CCCD.
- Confirm, manual assign, reassign, detach, not-found, invalid packet, and
  stale-conflict responses.
- Restart preserves candidates and confirmed mappings.
- Case deletion removes every CCCD asset.
- Path-based image access is impossible.

### Frontend tests

- Third upload accepts `.xlsx` and passes the selected file.
- Progress label for the `cccd` stage.
- Case banner counts and `Xử lý CCCD` visibility.
- Mapping panel renders paired, incomplete, suggested, unmatched, and conflict
  rows without exposing full CCCD in list copy.
- Name suggestion requires an explicit confirmation.
- Packet selector, confirm, reassign, detach, cancel, loading, 409 refresh, and
  retry states.
- Dashboard attention reasons remain orthogonal to lifecycle status.
- Confirmed packet manifest renders Excel CCCD tabs and source focus.

### End-to-end acceptance

Use a generated synthetic workbook containing at least:

- one exact-CCCD front/back pair;
- one unique name-only pair;
- one unreadable or unmatched image;
- one incomplete pair; and
- media filenames whose lexical order differs from drawing order.

Verify:

1. exact match attaches automatically;
2. name-only does not attach until confirmation;
3. unmatched remains in the queue;
4. attention appears and clears correctly;
5. mapped documents survive reload/backend restart;
6. reassignment changes the correct packet without duplication;
7. existing review and report behavior is unchanged;
8. full frontend/backend suites and production build pass; and
9. browser QA at `http://127.0.0.1:5174/` has no console errors.

No real CCCD image or identity may appear in a test fixture, snapshot,
documentation example, or QA artifact.

## Acceptance Criteria

1. A reviewer can supply a CCCD image workbook during case creation.
2. The backend extracts original embedded PNG/JPEG drawings without relying on
   worksheet cell data or media filename order.
3. Only a high-confidence, unique roster-backed exact CCCD match attaches
   automatically.
4. Every name-only match requires explicit human confirmation.
5. Ambiguous or unreadable candidates are preserved for manual assignment
   rather than dropped or guessed.
6. Confirmed images appear inside the correct packet as CCCD evidence.
7. Supported identity sources link to the correct image regions.
8. Attach, detach, and reassign are persistent and idempotent.
9. CCCD mapping attention never changes reviewer lifecycle, packet completion,
   rejection, or report state.
10. Existing cases and uploads without a CCCD workbook behave exactly as
    before.
11. All CCCD processing remains local, deletion removes all derived assets, and
    no real PII is committed or logged.
