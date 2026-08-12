# CTV Local CLI Foundation — Design

**Date:** 2026-08-12

**Status:** Approved design; implementation not started

**Product owner:** CTV/AP Review

**Consumer:** WePrompt agents and local operators

## 1. Decision

Build the CTV preprocessing capability as a standalone local command-line toolkit
owned by the CTV project. WePrompt (WP) agents call the toolkit from the user's
machine and interpret its bounded JSON responses.

WP does not contain, bundle, copy, or package the CTV runtime, validator, contract,
or generated artifacts. The toolkit does not depend on WP internals and can be run
directly by a person in Terminal.

This design supersedes the bundled WP extension, stdio MCP server, and copied WP
contract snapshot proposed in:

- `docs/superpowers/plans/2026-08-11-wp-ctv-preprocessing-tools.md`; and
- the tool-packaging portions of
  `docs/superpowers/specs/2026-08-11-weprompt-ctv-intake-assistant-design.md` and
  `docs/superpowers/plans/2026-08-11-wp-ctv-intake-assistant.md`.

The product intent in those documents remains valid: WP provides the conversation,
the toolkit performs deterministic local operations, original evidence is read-only,
and a human retains final authority.

## 2. Why this boundary

Keeping the toolkit outside WP provides one source of truth for preprocessing and
validation. A WP agent, another local agent, an automated test, and a human operator
all invoke the same commands and receive the same results. CTV can update and test
its file-processing implementation without coupling it to WP release packaging.

This boundary also avoids:

- adding CTV-specific dependencies to WP;
- shipping a second copy of the CTV contract or validator;
- requiring a background MCP service;
- relying on Bun, `npx`, a globally installed executable, or a WP extension loader;
  and
- allowing conversational behavior to redefine deterministic validation rules.

## 3. System boundary and ownership

```text
User
  |
  v
WP agent or local operator
  |
  | explicit local command with JSON output
  v
CTV local CLI toolkit
  |-- reads: selected original source root
  |-- reads/writes: separate CTV working root
  `-- uses: canonical CTV intake contract and validator
```

### WP agent owns

- conducting the conversation;
- obtaining the explicit toolkit path and, in later milestones, source and working
  folder selections;
- running documented commands without rewriting their meaning;
- explaining structured results and uncertainty; and
- requesting explicit user approval before a future write operation.

### CTV toolkit owns

- local file access and path-safety enforcement;
- deterministic inspection, transformation, package creation, and validation;
- resumable operation state in a separate working root;
- stable JSON and exit-code behavior; and
- the canonical CTV intake contract and its compatibility rules.

### User owns

- choosing the toolkit, source, and working locations;
- resolving questions the toolkit or agent cannot answer safely;
- approving proposed transformations; and
- the final accounting review and payment decision.

### Filesystem boundary

The original source root is always read-only. All state and derived outputs belong
in a distinct working root. A future command must reject a working root that is the
source root, is inside it, resolves to it through links, or would otherwise cause a
write into original evidence.

The foundation milestone does not accept a source root or a working root and does
not inspect user documents.

## 4. Foundation milestone

The first milestone proves that the local toolkit is identifiable, healthy, and
bound to the approved contract before any document-processing command is designed.

It adds one CLI entry point in the CTV repository:

```text
server/ctv_intake_cli.py
```

It exposes only these read-only commands:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py version --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py doctor --json
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py contract verify --json
```

The examples show the interface, not a fixed installation path. The caller supplies
the toolkit path explicitly. Commands must work from any current working directory,
including when the repository path contains spaces or Vietnamese characters.

### `version --json`

Returns:

- toolkit name and semantic version;
- CLI response schema version;
- supported intake compatibility target;
- approved contract source commit; and
- approved contract tree SHA-256.

This command performs no document or network access.

### `doctor --json`

Checks only the dependencies required to start the toolkit and run the canonical
contract validator. It reports whether the local environment is ready and provides
bounded recovery codes for missing or incompatible dependencies.

It does not inspect user documents, mutate dependencies, install software, access
the network, or claim that any payment package is correct.

### `contract verify --json`

Verifies the complete local `contracts/ctv-intake/v1/` tree against the approved
pin. The calculation follows `contracts/ctv-intake/README.md`, includes every
regular file below `v1/`, and detects added, missing, or modified files.

The approved pin is:

```text
sourceCommit: 75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a
contractTreeSha256: 83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d
compatibilityTarget: ctv-intake-v1
```

Implementation will store this metadata outside the hashed `v1/` tree so the pin
does not change the content it identifies. Contract verification reads local bytes;
it does not silently restore them or fetch a replacement.

## 5. Stable machine interface

In JSON mode, standard output contains exactly one UTF-8 JSON object followed by a
newline. Human progress messages, logging, banners, and stack traces never appear on
standard output.

Every command returns this envelope:

```json
{
  "schemaVersion": "1.0",
  "operation": "doctor",
  "status": "succeeded",
  "summary": "Local CTV toolkit is ready",
  "result": {},
  "errors": [],
  "retryable": false
}
```

Required envelope semantics:

- `schemaVersion` is exactly `1.0` for this interface.
- `operation` is the stable command identifier: `version`, `doctor`, or
  `contract.verify`.
- `status` is `succeeded` or `failed`. Foundation commands do not return partial
  success.
- `summary` is concise, user-safe, and contains no sensitive absolute path.
- `result` is a command-specific object and is empty when no safe result exists.
- `errors` is an ordered array of structured errors with stable `code` and safe
  `message` fields. It contains no raw exception or document data.
- `retryable` tells the agent whether repeating the same operation could be useful
  after the stated recovery action.

JSON field ordering and error ordering are deterministic so snapshots and agent
parsers remain stable. Additional fields require a schema-version decision; callers
must not infer meaning from undocumented fields.

### Exit codes

- `0`: the requested check succeeded.
- `2`: the request was valid, but a user-correctable environmental or contract
  problem was found.
- `1`: invocation, configuration, or unexpected toolkit failure prevented a valid
  check.

A failed command must return `status: "failed"`. A successful command must return
`status: "succeeded"`. The exit status and envelope may not contradict each other.

## 6. WP invocation protocol

The WP agent receives an explicit path from the user or workspace configuration. It
must not scan the machine, guess among repository copies, use the shell search path,
or silently switch toolkits.

Before any later document-processing workflow, the agent runs these preflight
checks in order:

1. `version --json` to verify the response schema, compatibility target, source
   commit, and contract hash expected by its instructions.
2. `doctor --json` to verify the local runtime.
3. `contract verify --json` to verify the local contract bytes.

The agent parses standard output as JSON and checks the process exit code. It stops
on invalid JSON, an unknown schema version, an incompatible contract identity, a
failed doctor check, a contract mismatch, or contradictory status and exit code.
It explains the provided recovery action instead of improvising a workaround.

WP instructions for these calls are a later milestone. This foundation changes no
WP code or repository content.

## 7. Safety and failure behavior

- Foundation commands perform no network request and start no background service.
- They do not enumerate, open, or report on user documents.
- They do not install, upgrade, repair, or delete software or contract files.
- Caller-provided strings are passed as argument values, never interpolated into a
  generated shell command.
- Controlled errors use synthetic identifiers rather than sensitive local paths.
- Raw Python exceptions and stack traces are suppressed from machine-facing output.
- A contract mismatch is non-retryable until the local toolkit is intentionally
  repaired or upgraded.
- A missing dependency is retryable only after the user completes the stated
  recovery action.
- If the CLI cannot construct its normal envelope, it exits `1`; tests must minimize
  this boundary and prove expected failures still produce valid JSON.
- A successful preflight means only that the toolkit and contract are ready. It is
  not evidence that an intake package is complete, accurate, accepted, or approved.

## 8. Testing and acceptance

The milestone is accepted only when all of the following are demonstrated from a
clean CTV checkout:

### Interface tests

- Each of the three commands returns an envelope valid against the `1.0` response
  model.
- Standard output contains only the single JSON object and trailing newline.
- Expected success, user-correctable failure, and toolkit failure exercise exit
  codes `0`, `2`, and `1` without status contradictions.
- Repeated calls under the same conditions return semantically identical results.

### Contract tests

- The approved contract tree passes.
- A modified file fails.
- A missing file fails.
- An unexpected added file fails.
- A wrong pinned hash or compatibility target fails.
- Failure output does not reveal the repository's absolute path.

### Launch tests

- Commands work when the current directory is outside the repository.
- Commands work when the repository path contains spaces and Vietnamese characters.
- The documented Terminal invocation and an automated agent invocation produce the
  same parsed envelope and exit code.
- Tests fail if a command attempts network access or document inspection.

### Regression gates

- The complete CTV backend test suite passes.
- The complete CTV frontend test suite passes.
- The production frontend build passes.
- The tracked diff is limited to the approved CLI foundation implementation, tests,
  and documentation.
- No real client data, local absolute path, secret, or generated dependency output
  is committed.

## 9. Milestone boundaries

### Included

- the local CLI entry point;
- the stable JSON envelope and exit-code contract;
- toolkit identity and contract pin metadata;
- runtime health checks;
- local contract-tree verification;
- safety, deterministic-output, and launch tests; and
- operator documentation for the three foundation commands.

### Excluded

- changes to the WP repository;
- a WP extension, MCP server, background daemon, or bundled runtime;
- global installation or automatic toolkit discovery;
- folder inventory or document inspection;
- OCR, AI classification, or proposed file organization;
- transformation approval or derived package writing;
- package validation through the new CLI;
- real client files; and
- push, release, deployment, or direct submission to CTV Review.

## 10. Delivery sequence after the foundation

Later work proceeds as independent CLI milestones, each designed and accepted before
WP instructions rely on it:

1. read-only folder inventory with bounded evidence identifiers;
2. safe document inspection and classification;
3. proposed organization and transformations with explicit user approval;
4. transactional derived-package creation with resumable recovery;
5. canonical package validation using the immutable source root; and
6. WP assistant instructions and conversational acceptance testing.

Every milestone must be usable and testable directly from Terminal. WP remains an
orchestrator and never substitutes model confidence for deterministic coverage or
human approval.
