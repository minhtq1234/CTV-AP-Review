# server/ — OCR/extract (Stage A) + FastAPI backend (Stage B)

`ocr_extract.py` renders + OCRs a source PDF's page range, segments it into
its constituent documents (`classify_page`/`segment_docs` — Hợp đồng, Biên
bản nghiệm thu, Bản cam kết, Phụ lục, Tra cứu thuế, CCCD), and extracts each
field's sources per document, returning `{"folder": {docs, fields}, "identity":
{cccd, name}}`. The `folder` shape matches `src/ctv/types.ts`'s `CtvFolder`
(minus `expected`, which isn't known yet) so it loads straight into the
existing reviewer (`FolderReview`) with no new UI, once the caller fills it
in.

`pipeline.py` orchestrates the packet splitter (`splitter/detect_packets.py`)
and `ocr_extract.py` into one call: split the source PDF into per-CTV
packets, OCR/segment each packet, then align it to its roster row by OCR'd
identity — `match_roster`: exact CCCD match, falling back to name — rather
than by packet position (a single swap or boundary shift used to mispair a
packet and cascade to the rest). The matched row fills each field's
`expected` (`fill_expected`) and the folder's name/product before the
manifest is written; an unmatched packet is flagged `"roster-unmatched"`
instead of being silently paired to the wrong row. `cases.py` is the
persistent `CaseStore` (JSON-on-disk under `data/cases/<id>/`) each upload
becomes a durable **case** in; `report.py` is a pure builder
(`build_report(case, manifests, generated_at)`) that groups the packets
still needing resubmission and renders the consolidated Markdown/CSV report;
`app.py` is the FastAPI service that runs the pipeline on a background
thread and exposes cases over HTTP (upload, poll, serve manifests + page
PNGs, save per-packet reviews, generate + serve the resubmission report) for
the frontend's upload flow.

## Running the tests

```bash
cd server
python3 ocr_extract_test.py     # plain-assert, no framework
python3 pipeline_test.py        # plain-assert, no framework (match_roster, roster indexing)
python3 cases_test.py           # plain-assert, no framework (CaseStore, status/progress)
python3 app_test.py             # the pytest-free subset (rewrite, validation, traversal, 404s)
python3 -m pytest app_test.py -q   # full suite, incl. the monkeypatched-pipeline tests
```

Only pure logic is unit-tested this way (word scaling/line grouping/bbox
union/anchor matching/page classification in `ocr_extract`; roster indexing
and identity matching in `pipeline`; case persistence + status/progress
recomputation in `cases`; URL rewriting/validation/routing in `app`, with
the real pipeline monkeypatched out). `ocr_packet`/`run_pipeline`'s I/O
layer (PyMuPDF render + pytesseract OCR) has no unit test — it wires
together already-tested pure logic around real PDF/OCR I/O, and is verified
by running the real file through the server (below).

## Running the server

```bash
cd server
python3 -m uvicorn app:app --host 127.0.0.1 --port 8001
```

Binds `127.0.0.1` only — this is a local, single-user tool, not a hosted
service. CORS allows the Vite dev origins (`localhost`/`127.0.0.1`, ports
5173-5175).

## Checking the standalone CTV toolkit

The caller supplies the explicit local path to the script. These commands work
from outside the checkout, so the current working directory does not need to be
the CTV repository:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py version --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py doctor --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py contract verify --json
```

Before any future CTV processing, a WP agent must run `version`, then `doctor`,
then `contract verify`, and stop if a check fails. Exit code `0` means the check
succeeded, and `2` means a valid check found a user-correctable environment or
contract problem. Exit code `1` means invalid invocation, a safely handled
structural or configuration failure that prevents a valid check, or an unexpected
toolkit failure. For a parsed `--json` operation, stdout contains JSON only.

These foundation commands do not accept document folders and do not write files.
WP contains no CTV implementation and performs no automatic toolkit discovery;
the toolkit path must be supplied explicitly. A successful preflight establishes
only toolkit, runtime, and contract readiness. It does not validate or approve a
payment package.

### Inventorying a source folder

Run the three preflight checks in order and stop if any check fails. Then select
one source folder explicitly and run the exact inventory command:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py version --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py doctor --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py contract verify --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py inventory --source-root /explicit/local/source --json
```

The toolkit does not discover a source folder automatically. The caller chooses
the `--source-root`; the inventory output uses opaque evidence and duplicate-group
IDs and contains no source filenames or paths. Evidence IDs describe one
deterministic observation and are not stable after the folder changes.

Inventory derives `detectedType` only from bounded leading-byte signatures. The
normalized extension is returned separately as a safe syntax hint and never
overrides the detected bytes. Exact-byte SHA-256 matches form duplicate groups;
matching names or similar content do not. Archives are opened only as ordinary
regular files for the bounded signature sample and, within the hashing limits, the
byte stream used for SHA-256. They are never parsed, decompressed, listed, or
extracted. Files above the per-file hash limit, and files reached after the total
hash budget is exhausted, remain listed without a digest and carry an item issue.

Item issues produce `complete-with-issues` while the inventory operation still
succeeds. A source that cannot be safely and completely observed produces an
operation-level failure instead of a partial inventory. The fixed limits are:

- maximum depth: 32;
- maximum directories: 2,000;
- maximum regular files: 10,000;
- maximum total items: 10,000;
- maximum total entries: 12,000;
- signature sample per regular file: 16 KiB;
- maximum hashed size per file: 256 MiB;
- maximum total hashed bytes: 2 GiB; and
- maximum canonical JSON output: 16 MiB, including the CLI envelope.

Inventory is read-only, keeps no state, writes no files, and makes no network
requests. A successful inventory establishes only a private-safe listing of the
explicit source folder under these limits. It does not establish document
completeness, case assignment, or payment approval.

### Inspecting document units

Run the same three preflight checks in order and stop if any check fails. Then
select one source folder explicitly and use only this exact inspection command:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py version --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py doctor --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py contract verify --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py inspect --source-root /explicit/local/source --json
```

Each inspection creates a fresh, descriptor-bound observation of the selected
root and revalidates that observation before returning. It does not reuse an
earlier inventory. If the source changes, WP must run inspection again and rebind
any review notes to the new observation, evidence, and unit IDs; those IDs are
deterministic only for one unchanged observation.

Supported content is reduced to one safe unit per PDF page, workbook worksheet,
or standalone image. A unit can suggest only `payment-roster`,
`service-contract`, `acceptance-record`, `payment-tax-form`, `identity-front`,
`identity-back`, `shared-supporting-evidence`, `other-supporting-evidence`, or
`unknown`. Confidence is one of `high`, `medium`, `low`, or `none`. These are
fixed structural suggestions, not findings: conflicting, ambiguous, low/medium,
or issue-bearing units set `needsUserReview` and cannot be automatically
organized unless later deterministic grouping checks resolve the same
structural facts safely.

`doctor` requires callable PyMuPDF, OpenPyXL, Pydantic, Pillow image decoding,
and the intake validator. It reports the optional local OCR capability as
`localOcr: {available, language}`. When available, its only reported language is
`vie`; when unavailable, inspection still runs but image-based units may remain
uncertain with fixed issue codes. No executable path, runtime version, installed
language list, parser diagnostic, raw document/OCR/cell text, source path,
filename, or worksheet name is returned. A leading ZIP can enter OOXML preflight
only when bounded detection identifies an OOXML workbook and the name ends in
`.xlsx`, `.xlsm`, `.xltx`, or `.xltm`. Every other leading ZIP or RAR stays
opaque, including an ordinary `.zip` whose members happen to use OOXML marker
names; the toolkit does not list or extract its archive members.

PDF embedded text is requested only after a conservative page-content and
resource proof bounds parser expansion. Pages whose content streams, fonts,
images, color profiles, or other resources cannot be proved within those limits
fail closed with `inspection-parser-boundary-exceeded`; a byte cap is never
claimed after unbounded extraction. Bounded pages without sufficient embedded
text use the 150-DPI render/OCR path. Workbook roster signals are row-level:
`roster-column-pattern` requires payment/amount plus identity/name headers on one
row, and `roster-row-pattern` requires at least two following rows populated in
both categories. A lone employee-code-like cell is not a roster pattern.

Inspection uses these fixed ceilings:

- PDF source bytes: 256 MiB;
- PDF pages per source: 10,000;
- embedded text per PDF page: 64 KiB;
- workbook source bytes: 25 MiB;
- worksheets per workbook: 100;
- inspected cells per workbook: 100,000;
- retained characters per inspected cell: 256 before reduction to fixed signals;
- standalone image source bytes: 25 MiB;
- decoded pixels per image: 50,000,000;
- OCR units per operation: 500;
- OCR time per unit: 30 seconds;
- total OCR time per operation: 30 minutes;
- total public inspection units: 10,000; and
- complete canonical CLI JSON envelope: 16 MiB.

`inspectionStatus: complete` means the bounded observation produced no fixed
inspection issue code. `complete-with-issues` means at least one fixed source or
unit `issueCode` was emitted; both are successful CLI results with exit code `0`.
`needsUserReview` is a separate confidence/categorical-review signal: it can be
nonzero while `inspectionStatus` is `complete`, for example for a low-confidence
or `unknown` suggestion without an issue code. Controlled operation failures
return one fixed, nonretryable failed envelope and exit code `2`, with no partial
result. Invalid invocation and unexpected internal failure use exit code `1`;
invalid invocation leaves stdout empty.

Inspection is read-only and stateless. It creates no application files, temporary
files, cache files, output folders, or source changes and makes no network
requests. Before any preparation handoff, WP asks the reviewer to resolve the
bounded exception queue and spot-check collapsed organized groups as needed:

- Are the automatically selected roster and organized participant/shared groups
  correct for the case?
- For each exception cluster, what role and participant, shared, case, or
  exclusion target is correct?
- Are any pages, worksheets, images, or opaque archives missing or out of scope?
- Do OCR, encryption, over-limit, unreadable, ambiguity, or conflict issues need
  a safer source or manual review?
- Has a human given one final approval for the complete, exactly accounted
  proposal?

Inspection does not establish authenticity, ownership, completeness, package
readiness, or payment approval. A preparation proposal and any output-root write
boundary are separate, user-approved work and are not performed by this command.

The standalone CLI threat model excludes hostile code already executing in the
same Python interpreter and recursively inspecting private closures. Even if
such reflection recovers the private OCR registry invocation, that innermost
boundary still rechecks exact PNG bytes and enforces the 25-MiB input, 30-second
timeout, and 4-MiB output ceilings before or around the local runner.

### Reviewing a preparation proposal with WP

WP calls the toolkit installed on the user's local machine; WP does not bundle,
copy, or reimplement any CTV code. The local script path and source folder are
both explicit. Run the preflights first and stop if any one fails, then use only
this exact review command:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py version --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py doctor --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py contract verify --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py proposal review --source-root /explicit/local/source --json
```

The review command retains one read-only observation from inspection through
final revalidation. During the original inspection pass, bounded memory-only
collectors receive the private text and typed roster-candidate facts already
acquired locally, and reuse only opaque exact-duplicate IDs already computed by
inventory; they do not reopen, re-render, OCR, hash, or parse a source a second
time. A uniquely valid roster is selected automatically in the normal case.
Versioned deterministic checks then organize evidence into participant, shared,
case, and duplicate-exclusion groups. The temporary `127.0.0.1` screen shows
only the exception clusters plus collapsed organized groups for optional spot checks,
followed by one whole-proposal approval. The user may instead return a draft or
cancel. The collectors and review session are cleared on every terminal or
failure path before the CLI emits one JSON envelope. The command writes no
source, output, report, cache, draft, or package file and makes no external
network request.

The local review lasts no more than two hours and times out after five minutes of
inactivity. A timeout, browser/server failure, parser or source failure, or any
source-tree change returns a fixed failure with no partial proposal. Retry always
starts a fresh observation and a fresh review; a draft cannot be resumed.

Exit `0` returns one privacy-safe `approved`, `draft`, or `cancelled` result under
operation `proposal.review`. An approved result has `readyToPrepare: true`; draft
and cancelled results do not. Exit `2` is a controlled source/environment/session
failure, while exit `1` is invalid invocation or a fixed internal failure.
Invalid invocation leaves stdout empty. Parsed operations emit canonical JSON no
larger than 16 MiB.

CLI JSON contains only opaque observation, participant, evidence, and unit IDs;
fixed decisions, roles, scopes, issue/error codes; bounded counts; and the local
approval digest/status where applicable. The private matching collectors are
memory-only and have no public serialization. Names, identity values, roster
cells, paths, filenames, previews, raw OCR/text, tokens, ports, private notes,
and parser diagnostics stay local and are never returned to WP. WP receives the
same bounded fixed JSON envelope by calling the local script; no CTV executable,
runtime, or matching data is bundled into WP.

`proposal review` remains a read-only preview. It does not persist a draft or
create a package. Use the separate combined command below only when the user has
also selected an existing output parent and intends to prepare a package.

The 2026-08-13 acceptance snapshot used Python 3.14.3, PyMuPDF 1.27.2.3,
OpenPyXL 3.1.5, Pillow 12.1.1, and Pydantic 2.13.4. These are privacy-safe test
environment identifiers, not minimum-version promises. Dependency versions are
not added to the public v1 doctor JSON because that would widen its fixed schema.

### Preparing one local CTV v2 package

WP calls the toolkit script installed on the user's local machine. No CTV runtime,
script, plugin, or skill is bundled into WP. Before opening the selected source,
the combined command verifies the immutable v2 contract again. The recommended
preflight and exact preparation command are:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py version --target ctv-intake-v2 --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py doctor --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py contract verify --target ctv-intake-v2 --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py package prepare --source-root /explicit/local/source --output-root /explicit/local/output-parent --json
```

`--output-root` is an existing local parent directory for newly published
packages. It must be separate from the source tree. Opening it and proving the
separation writes nothing. The toolkit then retains one read-only source
observation, performs the same one-pass automatic roster selection and
deterministic organization, and opens the authenticated loopback review screen.
The user resolves only exception clusters, may spot-check collapsed organized
groups, and gives one final approval for the complete proposal. A draft,
cancellation, browser failure, or review failure writes no staging directory or
package and cannot be resumed. Any source change invalidates the proposal and
publishes nothing. Approval is consumed once in that same command; only then can
the transaction build, validate, revalidate, and atomically publish the package.

A successful prepared result uses operation `package.prepare`, exit `0`, and an
opaque directory name such as `ctv-package-0123456789abcdef01234567`. The JSON
contains only opaque package identity, fixed contract/digest fields, bounded
counts, fixed validation codes, and `readyForCtvReview: true`. It does not contain
the source or output path, original filenames, FA code, participant values,
roster cells, previews, OCR text, browser token/port, timestamps, staging name,
or raw parser diagnostics.

| Exit | Outcome | Meaning |
| --- | --- | --- |
| `0` | `prepared` | One new complete package was atomically published. |
| `0` | `draft` | Review ended without approval; nothing was written. |
| `0` | `cancelled` | The user cancelled; nothing was written. |
| `2` | failed envelope | A controlled source, output, collision, build, validation, or cleanup boundary stopped preparation. |
| `1` | invalid invocation or internal failure | Invalid argv leaves stdout empty; a parsed command uses a fixed private-safe failure. |

The final directory is deterministic. Repeating the same approved preparation
after success returns a controlled collision and never opens, changes, merges,
or replaces the existing package. Before atomic publication, a crash may leave a
hidden run-owned staging directory under the output parent. Later runs ignore it;
automatic broad staging cleanup is deliberately out of scope. If terminal stdout
fails after publication, the complete package remains in place and a retry meets
the same collision boundary.

The Darwin atomic no-replace rename is the publication point. Failures before
that rename publish no final package. The toolkit then attempts a best-effort
parent-directory sync for crash durability; if that later sync fails, it does not
report the already published complete package as a failed or unpublished run.
The command still returns the canonical `prepared` result, and an identical retry
meets the deterministic collision boundary.

`prepared` means the local package passed the mechanical v2 validator and is
ready to enter the existing CTV human review workflow. It does not prove evidence
authenticity, authorize payment, approve accounting treatment, identify the
reviewer, or submit anything to CTV or ACC. Human CTV review remains required.

#### Local acceptance and WP handoff

The executable generated acceptance gates are:

```bash
python3 -m pytest server/ctv_exception_review_acceptance_test.py -q
python3 -m pytest server/ctv_package_acceptance_test.py -q
```

They create only synthetic local inputs. The exception-first gate uses a unique
two-person roster, participant and shared PDFs, an exact duplicate, a real image,
one ambiguous page cluster, and an unsupported source. It proves that the first
screen reports exact unit coverage with zero unaccounted units, exposes only two
exception clusters plus collapsed groups, and never exposes the legacy flat unit
decision list. The package gate retains the detailed artifact and assignment
coverage. Together they use the real production-created grouped state,
authenticated exception API, one whole-proposal approval, writer, standalone v2
validator, and deterministic collision boundary. They also check source
immutability, privacy-safe canonical CLI JSON, and absence of hidden staging
after handled outcomes.

Before a WP handoff, run one draft-only pilot against the explicitly selected
real source and a new empty output parent. Stop with **Return draft** or
**Cancel** at the first exception-first screen; do not approve on the user's
behalf. Record only source/unit/group/exception counts, unaccounted units, and
time to first review state. Confirm that user actions scale with exception
clusters plus one final approval, no flat unit list appears, and the output
parent remains empty. A later approved pilot still requires the human reviewer
to resolve every exception and perform the final approval before standalone
validation and digest comparison.

If the pilot reports `roster-missing`, every atomic unit remains covered by
bounded exception-state source ranges, but the review is intentionally not
actionable or approvable. Correct the source roster and relaunch; do not invent
a participant, assignment, or roster candidate.

For an installed-user workflow, WP supplies the explicit script, source, and
existing output-parent paths and starts the exact `package prepare` command
above. The human works only in the loopback screen. WP receives the one bounded
JSON envelope, explains the fixed outcome and counts, and asks the user to review
the opaque package directory locally. WP does not read source or package content,
copy this runtime into a plugin, infer missing facts, approve payment, or submit
the result to CTV/ACC.

To recheck a published v2 directory mechanically, use:

```bash
python3 server/validate_intake_package.py \
  /path/to/ctv-package-opaque-id \
  --source-root /path/to/original-source
```

The writer alone creates the v2 `validation-report.json`; standalone v2
validation is read-only and rejects `--write-report`. A valid standalone result
proves current source/package/contract coherence, not that a particular browser
session or reviewer can be cryptographically authenticated later.

## Validating a prepared intake package

The CTV intake contract validator is a read-only mechanical gate for a prepared
package. From the repository root, run:

```bash
python3 server/validate_intake_package.py /path/to/package --source-root /path/to/workspace
python3 server/validate_intake_package.py /path/to/package --source-root /path/to/workspace --write-report
```

The second form is the legacy v1 report-writing path. For v2, the transactional
writer has already installed the canonical receipt and the standalone validator
must be invoked without `--write-report`.

The command writes one canonical `ValidationReport` JSON object to stdout. It exits
`0` for a valid package and `2` for a completed validation with an invalid outcome.
Operational failures that prevent the requested command from completing use exit
`1` and write diagnostics only to stderr.

`--source-root` supplies the original read-only workspace used by manifest
`sources[].path`. It is required for a `valid`/`prepared` result: omitting it, or
supplying a missing, unsafe, or symlinked root, produces a normal invalid report
without disclosing the absolute source path. Every source is read without following
symlinks, checked against its declared byte size and SHA-256, and PDF page counts are
verified from that same bounded byte snapshot. V1 caps PDF originals at 256 MiB,
workbook originals at 25 MiB, other originals at 100 MiB, and actual PDFs at 10,000
pages. Source files are never written or normalized.

`--write-report` atomically writes the exact stdout bytes to the fixed package-local
path `validation-report.json`. It accepts no caller-selected destination, refuses
symlink/non-directory package roots and symlink/non-regular targets, and will not
overwrite a digest-pinned `validation-report.json` artifact declared by the
manifest. The validator never rewrites the manifest, original inputs, or other
artifacts.

This result means the package is mechanically complete against the CTV intake
contract. It does not approve payment evidence or authorize submission to CTV. See
`contracts/ctv-intake/README.md` for the CTV-to-WP snapshot procedure.

### Endpoints

- `POST /api/cases` — multipart `pdf` (required) + `roster` (optional
  `.xlsx`). Creates a case dir under `data/cases/<id>/`, saves both files
  into it, starts the pipeline on a background thread, returns
  `{"case_id": "..."}`.
- `GET /api/cases` — list of `{id, name, createdAt, status, pdfName,
  progress: {done, total, flagged}}`, newest first.
- `GET /api/cases/{id}` — the full case: `{id, name, createdAt, status,
  pdfName, rosterName, summary, error, packets, progress}` plus, while
  `status == "processing"`, a `liveProgress: {stage, done, total, detail}`
  (`stage` goes `"splitting"` -> `"ocr"`). `status` is `processing` /
  `ready` / `in_review` / `done` / `error`; each packet in `packets[]` has
  `{index, name, pages, confidence, flags, review, matchedBy, ocrIdentity,
  rosterIdentity, ...}`:
  - `review: {done, fields: {<fieldKey>: {seen, flag}}}` — `flag` is
    `null` or `{reason, note}`; `done` is set once the reviewer has
    worked through every field.
  - `matchedBy` is how the packet was aligned to the roster:
    `"cccd"` / `"name"` / `"unmatched"` / `"no-roster"`.
  - `ocrIdentity: {cccd, name}` is the identity OCR'd off the packet;
    `rosterIdentity: {cccd, name} | null` is the matched roster row's
    identity (`null` when `matchedBy` is `"unmatched"`/`"no-roster"`).
- `PUT /api/cases/{id}/packets/{i}/review` — body `{"done": bool,
  "fields": {<fieldKey>: {"seen": bool, "flag": null | {"reason", "note"}}}}`.
  Persists the packet's review state, recomputes the case status, returns
  `{packet, progress, status}`. 404 for an unknown case or packet.
- `POST /api/cases/{id}/report` — builds the consolidated resubmission
  report (`report.build_report`) from the case's packets + their manifests,
  writes `report.md`/`report.csv` into the case dir, and returns
  `{groups, markdown, csv}`. Only packets still needing resubmission
  (a flagged field, or a weak/`"name"`/`"unmatched"` roster match) are
  included.
- `GET /api/cases/{id}/report.md` / `GET /api/cases/{id}/report.csv` — the
  last-generated report file for the case, served as an attachment. 404 if
  `POST .../report` hasn't been called yet.
- `DELETE /api/cases/{id}` — removes the case dir + index entry.
- `GET /api/cases/{id}/packets/{i}/manifest.json` — that packet's
  `CtvFolder` manifest, with every page's `src` rewritten from the on-disk
  path to `/api/cases/{id}/packets/{i}/page/{basename}`.
- `GET /api/cases/{id}/packets/{i}/page/{name}` — the rendered page PNG.
  `name` must match `^[A-Za-z0-9_.-]+\.png$` (400 otherwise) — a guard
  against path traversal, since it's joined onto a directory path.

On startup, `CaseStore` scans `data/cases/*/case.json` and rebuilds its
index from disk, so cases (and saved reviews) survive a backend restart.

### Example: upload the real file, poll, fetch a manifest

```bash
curl -s -F "pdf=@/path/to/scan.pdf" \
        -F "roster=@/path/to/roster.xlsx" \
        http://127.0.0.1:8001/api/cases
# => {"case_id": "..."}

curl -s http://127.0.0.1:8001/api/cases/<case_id>       # poll until status == "ready"
curl -s http://127.0.0.1:8001/api/cases/<case_id>/packets/0/manifest.json
curl -s -X PUT -H 'content-type: application/json' \
     -d '{"done":true,"fields":{"cccd":{"seen":true,"flag":null}}}' \
     http://127.0.0.1:8001/api/cases/<case_id>/packets/0/review
curl -s -X POST http://127.0.0.1:8001/api/cases/<case_id>/report
curl -s http://127.0.0.1:8001/api/cases/<case_id>/report.md
```

## Roster -> field mapping, and packet alignment

`pipeline.all_roster_rows(rows)` maps every roster data row's Vietnamese
columns to the six field keys `ocr_extract.extract_fields` expects, plus a
product name:

| roster column          | field key  |
|-------------------------|------------|
| Họ và Tên               | `name`     |
| Số CCCD                 | `cccd`     |
| MST                     | `mst`      |
| Ngày Tháng Năm Sinh      | `ngaysinh` |
| Số TK                    | `tk`       |
| Phí dịch vụ              | `phi`      |
| Note (text before " - ") | product    |

`pipeline.build_roster_index(rows)` indexes all of them once, up front, by
`digits(cccd)` and by `norm(name)`. Each packet is then aligned to its row by
**identity**, not position: `match_roster(cccd, name, by_cccd, by_name)`
tries an exact CCCD match first, falls back to a name match (so a roster row
with a typo'd CCCD still aligns by name and correctly flags the CCCD field
as a mismatch, instead of not matching at all), and otherwise reports
`"unmatched"` — the packet gets flagged `"roster-unmatched"` rather than
silently paired to the wrong row. With no roster (`roster_path=None`), every
packet is `"unmatched"` — no expected values, no product.

## PII

The source PDF, roster spreadsheet, and every case directory (`case.json`,
manifests, page PNGs) this server reads or writes contain real personal
data (names, CCCD, MST, bank accounts, dates of birth). All of it lives
under `server/data/` — gitignored, never committed:

- `server/data/` itself (the whole tree — `.gitignore` has `server/data`),
- the source PDF or roster spreadsheet,
- any `case.json`, `manifest.json`, or page PNG produced by a case or by
  `render_pages`/`ocr_packet` run offline,
- ad-hoc driver scripts that point at real files.

Only the server modules and their tests (synthetic/fake data) belong in
git. Before committing, `git status` should show none of the above.
