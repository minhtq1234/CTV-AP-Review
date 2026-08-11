# WP CTV Preprocessing Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver bounded, local WP tools that inventory inconsistent CTV input folders, inspect PDFs/workbooks/archives, preview deterministic changes, create versioned derived packages, and validate them against the pinned CTV contract without mutating source files.

**Architecture:** A first-party WP extension contributes one local stdio MCP server. The server is a thin protocol adapter over pure TypeScript modules. It treats the selected source directory as read-only, persists resumable batch facts under the WP project workspace, writes only to `Prepared/`, and invokes the pinned CTV contract validator logic ported as deterministic TypeScript checks. AI is not part of these tools.

**Tech Stack:** TypeScript strict mode, Node.js APIs, `@modelcontextprotocol/sdk`, Zod, Vitest 4, `pdfjs-dist`, `pdf-lib`, `xlsx-republish`, `yauzl`, `node-unrar-js`, esbuild.

## Global Constraints

- Execute in a clean WP worktree created from a freshly fetched and explicitly confirmed `origin/sprint3` SHA. Never implement in the dirty local `main` checkout.
- Follow root `AGENTS.md`, `CONTRIBUTING.md`, and the project architecture/testing/i18n skills before editing.
- Do not commit `docs/superpowers/` in WP; these plans live in the CTV repository because that path is ignored in WP.
- Do not touch WP `main`; use a bounded `codex/ctv-intake-tools-v1` branch and no push or release unless separately authorized.
- The source root is read-only. `workspaceRoot` and `sourceRoot` must be distinct real paths, and `Prepared/` must not resolve inside `sourceRoot`.
- Reject symlinks, path traversal, special files, archive traversal, archive bombs, and output paths outside the project workspace.
- Raw file contents and PII never appear in logs, MCP error messages, model-facing summaries, snapshots, or test fixtures.
- All tools return bounded structured JSON plus a concise text summary. Large inventories are persisted and returned by stable evidence ID.
- No tool may label a package `prepared` until the deterministic validator passes. Individual case failure must not discard successful sibling cases.
- Direct submission to CTV is out of scope.

---

## Stable MCP Surface

Implement these exact v1 tool names:

```text
ctv_inventory_batch
ctv_inspect_documents
ctv_preview_transformations
ctv_prepare_case
ctv_validate_package
```

Every request includes `workspace_root` and either `source_root` or a previously returned `batch_id`. Every response includes:

```ts
type ToolEnvelope<T> = {
  schemaVersion: '1.0';
  operationId: string;
  batchId: string;
  status: 'succeeded' | 'partially_succeeded' | 'needs_user_input' | 'failed';
  summary: string;
  result?: T;
  exceptionIds: string[];
  retryable: boolean;
};
```

Persist state under `.weprompt/ctv-intake/batches/<batch-id>/`. Derived packages go only to `Prepared/<batch-id>/<fa-code>/vNNN/`.

## Task 1: Establish the WP worktree and pin the CTV contract

**Files:**

- Create: `extensions/ctv-intake/contracts/ctv-intake/v1/SOURCE.json`
- Copy from CTV: `extensions/ctv-intake/contracts/ctv-intake/v1/*.schema.json`
- Copy from CTV: `extensions/ctv-intake/contracts/ctv-intake/v1/exception-codes.json`
- Copy from CTV: `extensions/ctv-intake/contracts/ctv-intake/v1/compatibility.md`
- Create: `scripts/check-ctv-intake-contract.mjs`
- Create: `tests/unit/ctv-intake/contractSnapshot.test.ts`

- [ ] From `/Users/lap16603/Projects/WePrompt`, run:

```bash
git fetch origin
git rev-parse origin/sprint3
git status --short
git worktree list --porcelain
```

Expected: record an immutable sprint3 SHA; do not assume the branch value recorded in this plan is still current.

- [ ] Invoke `superpowers:using-git-worktrees` and create an isolated WP worktree/branch. Read `AGENTS.md`, `CONTRIBUTING.md`, `.claude/skills/architecture/SKILL.md`, `.claude/skills/testing/SKILL.md`, and `.claude/skills/i18n/SKILL.md` from that exact worktree before changing files.
- [ ] Run baseline verification:

```bash
bun run test
```

Expected: exit 0. If it stalls or is interrupted, record it as unverified and stop before implementation.

- [ ] After the CTV contract plan is accepted, copy the published contract files byte-for-byte and create `SOURCE.json` with exact source repository, CTV commit SHA, contract path, aggregate tree SHA-256, and copy timestamp.
- [ ] Write a failing snapshot test and script that reject edited schema bytes, an incorrect source digest, a missing file, or a major version other than `1`.
- [ ] Implement only the snapshot verifier; do not hand-edit the copied schema.
- [ ] Run:

```bash
bunx vitest run tests/unit/ctv-intake/contractSnapshot.test.ts
node scripts/check-ctv-intake-contract.mjs
```

Expected: PASS.

- [ ] Commit:

```bash
git add extensions/ctv-intake/contracts scripts/check-ctv-intake-contract.mjs tests/unit/ctv-intake/contractSnapshot.test.ts
git commit -m "chore(ctv-intake): pin CTV package contract"
```

## Task 2: Prove the extension and stdio runtime before building tools

**Files:**

- Create: `extensions/ctv-intake/aion-extension.json`
- Create: `extensions/ctv-intake/contributes/mcp-servers.json`
- Create: `extensions/ctv-intake/mcp/server.ts`
- Create: `extensions/ctv-intake/mcp/protocol.ts`
- Create: `scripts/build-ctv-intake-extension.mjs`
- Create: `tests/unit/ctv-intake/mcpProtocol.test.ts`
- Create: `tests/e2e/specs/ctv-intake-extension.e2e.ts`

- [ ] Add a failing unit test for `ToolEnvelope<T>` serialization and a failing E2E test that loads `extensions/`, sees `ctv-intake-tools`, starts the bundled stdio server, lists a temporary `ctv_runtime_probe` tool, and receives a fixed response without network access.
- [ ] Create the minimal extension manifest and MCP server. The build script must bundle the server and production dependencies into `extensions/ctv-intake/dist/ctv-intake-mcp.cjs` so the installed extension does not depend on the source tree or `bun`.
- [ ] Make the manifest launch Node with the extension-relative bundle. If the sprint3 extension loader does not resolve an extension-relative stdio entry point, stop here and file the smallest loader contract change; do not install a global executable, use `npx`, or embed a developer absolute path.
- [ ] Add the bundle to the extension packaging input, but do not check generated build output into git unless the existing WP extension packaging convention requires it.
- [ ] Run:

```bash
node scripts/build-ctv-intake-extension.mjs
bunx vitest run tests/unit/ctv-intake/mcpProtocol.test.ts
bunx playwright test tests/e2e/specs/ctv-intake-extension.e2e.ts
```

Expected: MCP process starts from the extension directory and the probe succeeds on macOS and the CI platform. This is a hard gate for later tasks.

- [ ] Commit source, tests, and required packaging metadata:

```bash
git add extensions/ctv-intake scripts/build-ctv-intake-extension.mjs tests/unit/ctv-intake/mcpProtocol.test.ts tests/e2e/specs/ctv-intake-extension.e2e.ts
git commit -m "feat(ctv-intake): scaffold local tool extension"
```

## Task 3: Implement path policy, durable state, and inventory

**Files:**

- Create: `extensions/ctv-intake/mcp/core/pathPolicy.ts`
- Create: `extensions/ctv-intake/mcp/core/ids.ts`
- Create: `extensions/ctv-intake/mcp/core/stateStore.ts`
- Create: `extensions/ctv-intake/mcp/core/inventory.ts`
- Create: `extensions/ctv-intake/mcp/core/types.ts`
- Create: `tests/unit/ctv-intake/inventory.test.ts`
- Create: `tests/unit/ctv-intake/stateStore.test.ts`

- [ ] Write failing tests for:
  - stable IDs derived from normalized relative path plus SHA-256;
  - deterministic lexical ordering independent of filesystem enumeration;
  - duplicate detection by digest;
  - unreadable and unsupported siblings retained as inventory entries;
  - symlinks, FIFOs, traversal, source/workspace overlap, and `Prepared/` inside the source root rejected;
  - atomic state writes and recovery from an interrupted temporary file;
  - retry reusing unchanged source facts while invalidating changed digests.
- [ ] Implement `ctv_inventory_batch` with bounded concurrency, byte/file/depth limits, no content logging, and stable exception codes from the pinned contract.
- [ ] The returned result contains counts by media type/state and the persisted inventory evidence ID; it does not return raw spreadsheet cells, OCR text, or identity values.
- [ ] Run targeted tests:

```bash
bunx vitest run tests/unit/ctv-intake/inventory.test.ts tests/unit/ctv-intake/stateStore.test.ts
```

Expected: PASS.

- [ ] Commit:

```bash
git add extensions/ctv-intake/mcp/core tests/unit/ctv-intake/inventory.test.ts tests/unit/ctv-intake/stateStore.test.ts
git commit -m "feat(ctv-intake): inventory immutable source batches"
```

## Task 4: Inspect ZIP/RAR, PDF, workbook, and image inputs safely

**Files:**

- Create: `extensions/ctv-intake/mcp/inspect/archiveInspector.ts`
- Create: `extensions/ctv-intake/mcp/inspect/pdfInspector.ts`
- Create: `extensions/ctv-intake/mcp/inspect/workbookInspector.ts`
- Create: `extensions/ctv-intake/mcp/inspect/imageInspector.ts`
- Create: `extensions/ctv-intake/mcp/inspect/inspectDocuments.ts`
- Create: `tests/unit/ctv-intake/inspectors.test.ts`
- Modify: `package.json`
- Modify: `bun.lock`

- [ ] Add `pdf-lib` and `node-unrar-js` through Bun so the lockfile captures exact versions. Review package license and packaged size before accepting the dependency change.
- [ ] Write failing synthetic tests for:
  - ZIP and RAR entry listing without extraction;
  - traversal, absolute entries, symlink-like entries, encryption, nesting, entry count, expanded bytes, and compression-ratio limits;
  - corrupt/password-protected archive isolated from successful siblings;
  - PDF page count, rotation, encrypted/corrupt state, and stable per-page evidence IDs;
  - all workbook sheets inspected, hidden/active state reported, header rows sampled, merged cells handled, and `CMND`, `CCCD/PP`, `Họ tên` retained as candidates rather than silently normalized;
  - image format/dimensions/EXIF rotation reported without OCR or raw bytes in the result.
- [ ] Implement `ctv_inspect_documents`. Archive contents remain virtual evidence until an approved prepare operation; inspection performs no derived write.
- [ ] Bound model-facing output to summaries and evidence IDs. Persist detailed structured facts in batch state.
- [ ] Run:

```bash
bunx vitest run tests/unit/ctv-intake/inspectors.test.ts
```

Expected: PASS.

- [ ] Commit:

```bash
git add package.json bun.lock extensions/ctv-intake/mcp/inspect tests/unit/ctv-intake/inspectors.test.ts
git commit -m "feat(ctv-intake): inspect mixed document batches"
```

## Task 5: Build transformation preview and approval invalidation

**Files:**

- Create: `extensions/ctv-intake/mcp/prepare/planSchema.ts`
- Create: `extensions/ctv-intake/mcp/prepare/preview.ts`
- Create: `tests/unit/ctv-intake/transformationPreview.test.ts`

- [ ] Write failing tests for a versioned case plan containing assignments, shared/duplicate/excluded/unresolved states, PDF page ordering/rotation, roster sheet/header mapping, archive selections, and target artifact paths.
- [ ] Assert that preview is deterministic for identical facts/decisions; any plan edit, source digest change, or tool-version change produces a new `proposalVersion` and invalidates prior approval.
- [ ] Assert preview refuses unknown evidence IDs, hidden pages, output collision, source overwrite, and a plan that claims complete coverage without explicit states.
- [ ] Implement `ctv_preview_transformations` as read-only. Return the target tree, operation list, coverage summary, exception summary, compatibility target, and an `approvalDigest` for the exact displayed version.
- [ ] Run:

```bash
bunx vitest run tests/unit/ctv-intake/transformationPreview.test.ts
```

Expected: PASS.

- [ ] Commit:

```bash
git add extensions/ctv-intake/mcp/prepare/planSchema.ts extensions/ctv-intake/mcp/prepare/preview.ts tests/unit/ctv-intake/transformationPreview.test.ts
git commit -m "feat(ctv-intake): preview versioned transformations"
```

## Task 6: Prepare derived case packages transactionally

**Files:**

- Create: `extensions/ctv-intake/mcp/prepare/pdfBuilder.ts`
- Create: `extensions/ctv-intake/mcp/prepare/rosterBuilder.ts`
- Create: `extensions/ctv-intake/mcp/prepare/packageWriter.ts`
- Create: `tests/unit/ctv-intake/packageWriter.test.ts`

- [ ] Write failing tests for copying/merging/reordering/rotating PDF pages with a complete source-page map, creating a canonical roster from the approved sheet/mapping, optional CCCD artifact handling, and manifest/artifact digests.
- [ ] Test transaction behavior: write to a private staging directory with mode `0700`, fsync files, validate before visibility, atomically rename to the next `vNNN`, and quarantine/remove only the incomplete staging tree on failure.
- [ ] Test that sibling case success survives one case failure and that retry reuses only artifacts whose source digests, approval digest, and tool version still match.
- [ ] Implement `ctv_prepare_case`. Require the exact current `approvalDigest`; never infer approval from conversational text.
- [ ] Build `exceptions.json` from every unresolved/unsupported/unreadable/excluded item and mark the manifest `partially_prepared` whenever blocking or unresolved evidence remains.
- [ ] Run:

```bash
bunx vitest run tests/unit/ctv-intake/packageWriter.test.ts
```

Expected: PASS and source-tree digest unchanged before/after each test.

- [ ] Commit:

```bash
git add extensions/ctv-intake/mcp/prepare tests/unit/ctv-intake/packageWriter.test.ts
git commit -m "feat(ctv-intake): write approved derived packages"
```

## Task 7: Validate against the pinned CTV contract

**Files:**

- Create: `extensions/ctv-intake/mcp/validate/schemaValidator.ts`
- Create: `extensions/ctv-intake/mcp/validate/semanticValidator.ts`
- Create: `extensions/ctv-intake/mcp/validate/validatePackage.ts`
- Create: `tests/unit/ctv-intake/packageValidation.test.ts`

- [ ] Port semantic rules from the accepted CTV validator without changing public codes. Add golden contract tests using the CTV complete, partial, and invalid-hidden-page fixture meanings.
- [ ] Write failing tests for schema mismatch, incompatible major version, digest mismatch, unreadable derived artifact, missing source/page coverage, unknown references, and false `prepared` status.
- [ ] Implement `ctv_validate_package`. It writes `validation-report.json` only when explicitly requested and only inside the selected package. Validation failure vetoes complete status.
- [ ] Compare WP report output with the CTV Python validator for the same generated synthetic packages. Require the same outcome and stable error-code set; wording may differ.
- [ ] Run:

```bash
bunx vitest run tests/unit/ctv-intake/packageValidation.test.ts
node scripts/check-ctv-intake-contract.mjs
```

Expected: PASS.

- [ ] Commit:

```bash
git add extensions/ctv-intake/mcp/validate tests/unit/ctv-intake/packageValidation.test.ts
git commit -m "feat(ctv-intake): validate packages against CTV v1"
```

## Task 8: End-to-end tool scenarios and packaging gate

**Files:**

- Create: `tests/e2e/specs/ctv-intake-tools.e2e.ts`
- Create: `tests/fixtures/ctv-intake/README.md`
- Create: `tests/fixtures/ctv-intake/generate.mjs`
- Modify: `scripts/build-ctv-intake-extension.mjs`

- [ ] Generate synthetic fixtures at test time for multiple FA folders, ZIP/RAR inputs, non-active roster sheets, header variants, shared/unassigned leading pages, duplicates, one corrupt item, and an intentionally partial case.
- [ ] Exercise all five MCP tools through the packaged extension process. Assert: source digests unchanged, every file/page has an explicit state, one failing case does not erase siblings, approval invalidates after edit, and no report claims complete with hidden evidence.
- [ ] Run:

```bash
node scripts/build-ctv-intake-extension.mjs
bunx playwright test tests/e2e/specs/ctv-intake-tools.e2e.ts
bun run test
bun run lint
bunx tsc --noEmit -p tsconfig.json
node scripts/check-i18n.js
git diff --check
```

Expected: all commands exit 0 and coverage for new logic is at least 80%.

- [ ] Inspect the produced extension archive: no source maps with local paths, no fixtures containing PII, no network dependency, and all runtime dependencies included.
- [ ] Commit:

```bash
git add tests/e2e/specs/ctv-intake-tools.e2e.ts tests/fixtures/ctv-intake scripts/build-ctv-intake-extension.mjs
git commit -m "test(ctv-intake): cover local preprocessing workflow"
```

## Task 9: Local real-batch acceptance (never committed)

- [ ] Use the approved local pilot-data workspace outside git. Record before/after source-tree hashes.
- [ ] Run the packaged tools against `CTV AP GAS` and require:
  - four proposed FA case inputs exposed for assistant review;
  - all top-level files and archive entries inventoried;
  - all relevant workbook sheets and header variants visible;
  - unsupported CCCD PDFs, loose/archive images, and multi-PDF cases visible;
  - all 32 unassigned pages in `FA-PM260706029` reported;
  - successful sibling cases retained when another is blocked or partial;
  - no original byte changed; and
  - zero packages labeled complete with hidden unresolved evidence.
- [ ] Save only a redacted acceptance summary containing counts, stable exception codes, tool/contract versions, and hashes that cannot reveal identity values. Do not add real paths, filenames containing names, thumbnails, OCR text, or documents to git.
- [ ] Do not push, publish, or install for other users until independent review and packaged acceptance are explicitly approved.

## Plan Self-Review Checklist

- [ ] Each conceptual tool in Section 11 of the design has an exact bounded implementation or is explicitly assigned to the assistant plan (`propose_case_plan`).
- [ ] Random/multiple files, ZIP/RAR, all workbook sheets, multiple PDFs, and image inputs are covered.
- [ ] Source immutability, output containment, approval digest, atomic writes, partial success, and item-level retry are tested.
- [ ] MCP responses minimize PII and never return unbounded raw extraction.
- [ ] The runtime/packaging gate proves the extension works without developer absolute paths or network installs.
- [ ] No `submit_to_ctv` tool exists in v1.
- [ ] A placeholder scan finds no unfinished markers in implementation or tests.
