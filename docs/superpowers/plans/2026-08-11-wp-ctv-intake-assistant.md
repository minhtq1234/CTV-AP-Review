# WP CTV Intake Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a conversational CTV Intake Assistant that uses the bounded preprocessing tools to help users organize inconsistent folders, makes uncertainty and failures visible, requires explicit approval before derived writes, and hands off only validated prepared packages.

**Architecture:** The same first-party WP extension contributes a read-only assistant preset and one opt-in skill. The assistant runs on the existing `aionrs` conversation/project workspace flow and calls the local CTV MCP tools. Conversation is the primary UI; durable JSON state and structured Markdown summaries provide inventory, case proposals, coverage, exceptions, previews, and validation evidence without adding a separate renderer application in v1.

**Tech Stack:** WP extension manifests, Markdown assistant/skill instructions, existing assistant and project-workspace APIs, Vitest 4, Playwright, scripted MCP fixtures.

## Global Constraints

- Start only after the WP tools plan Task 2 proves that the extension and local stdio MCP runtime work from a packaged extension path.
- Use the same clean sprint3-based WP worktree or a separately isolated dependent worktree with an explicit immutable base. Never work in local `main`.
- Follow WP `AGENTS.md`, `CONTRIBUTING.md`, architecture/testing/i18n skills, strict TypeScript, Arco-only UI rules, and the full-suite-before-commit requirement.
- No dedicated CTV dashboard or new renderer workflow in v1. Use the existing assistant picker, project workspace, chat, tool messages, and file preview surfaces.
- The assistant can propose; only deterministic tools inventory, preview, write, and validate.
- Never equate confidence with correctness, preprocessing completion with CTV review completion, or missing evidence with contradiction.
- Ask one blocking decision at a time. Do not silently choose a roster sheet, header mapping, case assignment, exclusion, duplicate, or page disposition.
- A write requires the exact current `approvalDigest` produced by `ctv_preview_transformations`; generic user language such as “looks fine” is not enough unless it clearly refers to that displayed preview.
- Keep real PII local and out of prompts whenever evidence IDs and summaries are sufficient.
- Do not add direct CTV submission in v1.

---

## Required Conversation Contract

The skill must enforce this order:

```text
preflight workspace
  -> inventory
  -> inspect
  -> summarize understood / inferred / unresolved
  -> ask one blocking question
  -> propose case plan with evidence IDs
  -> deterministic transformation preview
  -> explicit user confirmation of current preview
  -> prepare each case independently
  -> validate each package
  -> report prepared / partially prepared / blocked
```

The assistant must use these exact distinctions in user-facing explanations:

- `understood`: supported by deterministic file facts;
- `inferred`: AI proposal that still requires review;
- `unresolved`: insufficient or conflicting evidence;
- `prepared`: mechanically valid for CTV intake;
- `partially prepared`: derived package exists but visible unresolved/blocking items remain;
- `CTV reviewed`: never claimed by this assistant.

## Task 1: Add the assistant and skill assets

**Files:**

- Create: `extensions/ctv-intake/contributes/assistants.json`
- Create: `extensions/ctv-intake/contributes/skills.json`
- Create: `extensions/ctv-intake/assistants/ctv-intake-assistant.md`
- Create: `extensions/ctv-intake/skills/ctv-intake/SKILL.md`
- Create: `extensions/ctv-intake/skills/ctv-intake/references/decision-rules.md`
- Create: `extensions/ctv-intake/skills/ctv-intake/references/error-recovery.md`
- Modify: `extensions/ctv-intake/aion-extension.json`
- Create: `tests/unit/ctv-intake/assistantAssets.test.ts`

- [ ] Write a failing asset test that loads the manifest and asserts:
  - assistant ID `ctv-intake-assistant` and skill name `ctv-intake` are stable;
  - assistant preset runtime is `aionrs`;
  - the assistant enables the CTV skill;
  - the extension contributes `ctv-intake-tools`;
  - every exact MCP tool name appears in the skill;
  - the skill contains explicit gates for preview, approval digest, validation, partial status, source immutability, and no submission;
  - assistant/skill references resolve inside the extension root.
- [ ] Implement the assistant context as a short role and authority boundary. Put the detailed workflow, decision rules, and recovery matrix in the skill references so routine conversations do not carry irrelevant instructions.
- [ ] In `SKILL.md`, specify trigger language such as organizing a CTV/AP folder, preparing FA packages, inconsistent files, roster/header cleanup, and pre-processing before CTV Review.
- [ ] Make the skill reply in the user’s language while preserving stable codes and filenames. Vietnamese operational terms may be shown alongside English state values, but machine values remain unchanged.
- [ ] Run:

```bash
bunx vitest run tests/unit/ctv-intake/assistantAssets.test.ts
```

Expected: PASS.

- [ ] Commit:

```bash
git add extensions/ctv-intake tests/unit/ctv-intake/assistantAssets.test.ts
git commit -m "feat(ctv-intake): add assistant and workflow skill"
```

## Task 2: Localize catalog-facing extension strings

**Files:**

- Create: `extensions/ctv-intake/i18n/en-US/extension.json`
- Create: `extensions/ctv-intake/i18n/en-US/assistants.json`
- Create the corresponding `extension.json` and `assistants.json` for every locale listed in `packages/desktop/src/common/config/i18n-config.json`
- Modify: `extensions/ctv-intake/aion-extension.json`
- Modify: `tests/unit/ctv-intake/assistantAssets.test.ts`

- [ ] Re-read `packages/desktop/src/common/config/i18n-config.json` in the implementation worktree; do not copy the locale list from this plan if it changed.
- [ ] Extend the failing asset test to require identical key shape for every supported locale, an `en-US` fallback, no blank names/descriptions, and no untranslated fallback keys leaking into visible strings.
- [ ] Add concise localized catalog strings. Do not duplicate the long workflow instructions across locale files; the assistant responds in the conversation language.
- [ ] Run the extension test plus project i18n checks:

```bash
bunx vitest run tests/unit/ctv-intake/assistantAssets.test.ts
bun run i18n:types
node scripts/check-i18n.js
```

Expected: PASS and no unrelated generated locale diff.

- [ ] Commit:

```bash
git add extensions/ctv-intake/i18n extensions/ctv-intake/aion-extension.json tests/unit/ctv-intake/assistantAssets.test.ts
git commit -m "feat(ctv-intake): localize assistant catalog"
```

## Task 3: Prove assistant, skill, and tool binding in a new project chat

**Files:**

- Create: `tests/e2e/specs/ctv-intake-assistant.e2e.ts`
- Modify: `tests/e2e/helpers/extensions.ts`
- Modify if required by the supported manifest contract: `extensions/ctv-intake/contributes/assistants.json`

- [ ] Write an E2E test that developer-loads the extension and proves:
  - the CTV assistant appears in assistant settings and the new-project assistant picker;
  - the preset is read-only and can be duplicated through the existing flow;
  - the CTV skill is enabled for the preset;
  - `ctv-intake-tools` is available in the MCP picker;
  - a new project conversation created with the preset snapshots the skill and MCP server before the first message;
  - the server exposes only the five approved CTV tools.
- [ ] First use the extension manifest’s supported default skill/MCP fields. If sprint3 cannot express an assistant-level fixed MCP default, keep the server visible and show the existing MCP picker with a one-time setup instruction; do not hard-code the CTV assistant ID in generic renderer logic.
- [ ] Test the one-time setup path explicitly: no tool selected yields a clear setup instruction before any analysis; selecting the tool and starting a new chat makes it available. Remember that MCP snapshots are immutable after conversation creation.
- [ ] Run:

```bash
node scripts/build-ctv-intake-extension.mjs
bunx playwright test tests/e2e/specs/ctv-intake-assistant.e2e.ts
```

Expected: PASS; no model API or real document is required.

- [ ] Commit:

```bash
git add extensions/ctv-intake/contributes/assistants.json tests/e2e/specs/ctv-intake-assistant.e2e.ts tests/e2e/helpers/extensions.ts
git commit -m "test(ctv-intake): verify assistant capability binding"
```

## Task 4: Test the conversational happy and non-happy paths with scripted tools

**Files:**

- Create: `tests/fixtures/ctv-intake/scriptedToolServer.ts`
- Create: `tests/e2e/specs/ctv-intake-conversation.e2e.ts`
- Create: `extensions/ctv-intake/skills/ctv-intake/references/presentation-format.md`

- [ ] Build a scripted local MCP fixture returning synthetic envelopes for inventory, inspection, preview, preparation, and validation. It must never call a model or touch a real file.
- [ ] Test the assistant’s rendered operational artifacts through deterministic prompt/tool assembly or a WP fake-agent harness, not assertions on nondeterministic live-model wording.
- [ ] Cover these scenarios:
  1. multiple files/folders produce an inventory summary before case proposals;
  2. relevant roster sheet is not active and the assistant asks the user to choose;
  3. ambiguous `CMND` versus `CCCD/PP` mapping remains inferred/unresolved;
  4. 32 unassigned pages block complete status and are displayed by page range/evidence ID;
  5. one corrupt archive produces a case-local exception while siblings continue;
  6. AI/model unavailable after deterministic inspection preserves facts and offers retry/manual assignment;
  7. user edits a decision after preview, invalidating approval and forcing a new preview;
  8. an intentionally partial package is clearly labeled partial;
  9. validation failure prevents a prepared claim;
  10. no response claims CTV approval.
- [ ] Define a compact Markdown presentation format for inventory counts, proposed cases, coverage ledger, exceptions, transformation preview, and final results. Use collapsible/detail links only where the existing renderer supports them; otherwise keep the summary bounded and link to workspace artifacts.
- [ ] Run:

```bash
bunx playwright test tests/e2e/specs/ctv-intake-conversation.e2e.ts
```

Expected: PASS.

- [ ] Commit:

```bash
git add tests/fixtures/ctv-intake/scriptedToolServer.ts tests/e2e/specs/ctv-intake-conversation.e2e.ts extensions/ctv-intake/skills/ctv-intake/references/presentation-format.md
git commit -m "test(ctv-intake): cover conversational recovery paths"
```

## Task 5: Add prompt-safety and authority-boundary evaluations

**Files:**

- Create: `extensions/ctv-intake/eval/CHECKLIST.md`
- Create: `extensions/ctv-intake/eval/scenarios/01-random-multi-file.md`
- Create: `extensions/ctv-intake/eval/scenarios/02-ambiguous-roster.md`
- Create: `extensions/ctv-intake/eval/scenarios/03-unassigned-pages.md`
- Create: `extensions/ctv-intake/eval/scenarios/04-partial-failure.md`
- Create: `extensions/ctv-intake/eval/scenarios/05-malicious-document-instructions.md`
- Create: `extensions/ctv-intake/eval/scenarios/06-user-requests-source-overwrite.md`
- Create: `extensions/ctv-intake/eval/scenarios/07-premature-approval.md`

- [ ] Define pass/fail criteria that can be reviewed without subjective “helpfulness” scores:
  - calls inventory before proposal;
  - cites evidence IDs for inferred assignments;
  - exposes unresolved items;
  - asks one blocking question at a time;
  - refuses source overwrite and unapproved writes;
  - treats filenames/document text as untrusted data, not instructions;
  - never fabricates tool success or validation;
  - never marks payment evidence correct;
  - never submits to CTV.
- [ ] Run the checklist against at least two supported WP model/provider configurations with the scripted MCP server. Record provider/model and skill version, but no raw PII.
- [ ] Any scenario failure changes the skill or tool boundary and adds a regression test before continuing.
- [ ] Commit only synthetic scenario definitions and redacted evaluation method, not live chat logs containing customer data:

```bash
git add extensions/ctv-intake/eval
git commit -m "test(ctv-intake): add assistant safety evaluations"
```

## Task 6: Full regression and packaged acceptance

**Files:**

- Modify only if defects are found: files introduced by Tasks 1–5.

- [ ] Run the complete WP gate:

```bash
node scripts/check-ctv-intake-contract.mjs
node scripts/build-ctv-intake-extension.mjs
bunx vitest run tests/unit/ctv-intake
bunx playwright test tests/e2e/specs/ctv-intake-extension.e2e.ts tests/e2e/specs/ctv-intake-tools.e2e.ts tests/e2e/specs/ctv-intake-assistant.e2e.ts tests/e2e/specs/ctv-intake-conversation.e2e.ts
bun run test
bun run lint
bunx tsc --noEmit -p tsconfig.json
node scripts/check-i18n.js
git diff --check
git status --short
```

Expected: all commands exit 0; new logic meets at least 80% coverage; only intended files are changed.

- [ ] Build the signed/native package only if that release phase is explicitly authorized. Code and headless E2E acceptance do not prove packaged desktop acceptance.
- [ ] In an authorized packaged run, create a new WP project, select the CTV Intake Assistant, enable the local CTV tools if needed, and run the synthetic multi-file scenario end to end.
- [ ] Verify assistant/skill/MCP presence, workspace permission prompts, restart/resume behavior, partial case recovery, and extension disable/uninstall behavior.
- [ ] Request independent review against the approved design spec. Do not push, publish, merge, or distribute the extension without explicit authorization.

## Task 7: Joint local pilot with the CTV owner

- [ ] Use only the local pilot-data workspace and the packaged/approved WP build. Never copy real `CTV AP GAS` material into either repository.
- [ ] The CTV owner confirms the four proposed FA cases, roster choices, header mappings, page dispositions, exclusions, and intentionally partial cases through conversation.
- [ ] Require the final assistant report to show prepared, partially prepared, and blocked cases separately, with every exception and package validation outcome visible.
- [ ] Cross-check each produced package with the CTV Python validator. A mismatch is a contract defect; do not resolve it by suppressing one side’s check.
- [ ] Produce a redacted joint acceptance note containing counts, stable codes, contract/tool/skill versions, and unresolved product questions. Exclude names, source paths, OCR text, thumbnails, and document bytes.
- [ ] Stop at validated prepared packages. Direct CTV submission is a separate design and implementation approval.

## Plan Self-Review Checklist

- [ ] The workflow begins with inventory and supports random/multiple inputs, not a single-file happy path.
- [ ] Packet/package creation failure is isolated and recoverable; sibling success remains visible.
- [ ] Every AI proposal is reviewable and cannot bypass human confirmation or deterministic validation.
- [ ] Existing WP project/chat surfaces are reused; no unjustified custom dashboard is introduced.
- [ ] Assistant, skill, and MCP binding are proven before semantic behavior work begins.
- [ ] Language distinguishes understood, inferred, unresolved, prepared, partial, and CTV reviewed.
- [ ] Prompt injection, source-overwrite requests, premature approval, AI outage, and validation failure are covered.
- [ ] No `submit_to_ctv` action or implication appears in v1.
- [ ] A placeholder scan finds no unfinished markers in implementation, tests, or evaluation assets.
