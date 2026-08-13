# CTV Preparation Proposal Review Lean V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the local hybrid proposal-review workflow with strict external-boundary validation, trusted in-process state, and one bounded approved/draft/cancelled JSON result.

**Architecture:** Reuse the existing retained inventory observation and bounded inspection/parser helpers. One proposal module owns normal trusted state and proposal rules; one review module owns the memory-only session, previews, loopback HTTP API, and static hybrid UI; the existing CLI owns lifecycle and canonical emission after final source revalidation.

**Tech Stack:** Python 3.14 standard library, existing PyMuPDF/Pillow/OpenPyXL inspection code, HTML/CSS/vanilla JS, pytest, existing React/Vitest regression suite.

**Spec:** `docs/superpowers/specs/2026-08-14-ctv-preparation-proposal-review-lean-design.md`

## Global Constraints

- Exact command: `proposal review --source-root SOURCE --json`; operation `proposal.review`; envelope version `1.0`.
- Defend strict HTTP/API/parser/filesystem/CLI boundaries; internal Python objects created after validation are trusted.
- Do not test or block on reflection, `object.__setattr__`, closure inspection, or hostile code already inside the interpreter.
- Source stays read-only; review state stays memory-only; no package/draft/report/cache/temp/output files.
- No new dependency, contract snapshot change, frontend product screen, WP bundle, database, persistence, output writer, or non-loopback network access.
- Keep one retained observation from inspection through final approval and revalidation; emit no stdout before successful close/revalidation.
- Names, identities, roster values, filenames, previews, raw text/OCR, private notes, tokens, ports, and parser diagnostics never enter CLI JSON/stderr/logs.
- Limits: total session 2 hours; idle 5 minutes; request 1 MiB; public JSON 16 MiB; preview 25 MiB; existing parser/source/unit ceilings still apply.
- TDD and generated synthetic data only. Each task gets one implementation commit and one independent review. Up to one focused correction round per task; any residual beyond that is ruled against the lean threat boundary rather than recursively hardened.
- No push, merge, release, package preparation, or worktree cleanup without explicit user choice.

---

### Task 1: Trusted Proposal State and Roster Mapping

**Files:**
- Create: `server/ctv_proposal.py`
- Create: `server/ctv_proposal_test.py`
- Modify: `server/ctv_inspection.py`
- Modify: `server/ctv_inspection_test.py`

**Interfaces:**
- Consumes: caller-owned live `InventoryObservation`, `InspectionResult`, existing fixed roles/signals/issues, and bounded workbook snapshot parsing.
- Produces: `inspect_observation(observation) -> InspectionResult`; `ProposalState.from_inspection(observation, inspection)`; strict `select_roster(mapping)`, `set_unit_decision(mapping)`, `set_source_disposition(mapping)` API-boundary converters; `draft_result()`, `approval_summary()`, `approve(expected_digest)`, and `cancelled_result()` public dictionaries.

- [ ] **Step 1: Write RED tests for retained inspection and proposal rules**

Use generated opaque inspections and `.xlsx` roster bytes. Test:

- caller-owned observation inspection matches `inspect_source` but does not close it;
- explicit roster candidate selection and handles in usable row order;
- recognized name + identity columns, duplicate/blank/malformed rows, row/cell/text bounds;
- every unit/source-only record represented once;
- accepted/reassigned/excluded/unresolved rules, role/unit restrictions, individual/shared/case cardinality, fixed exclusion reasons;
- strict mapping inputs: exact dict/key sets, exact primitive types, regex IDs, enums, counts, no extra values;
- readiness only after every record resolves and no unknown role;
- deterministic digest changes for every decision and excludes local labels/notes;
- approved/draft/cancelled public shapes and no private values;
- source mutation at observation close invalidates any terminal result;
- ordinary internal dataclass mutation/reflection is not in test scope.

Representative boundary test:

```python
state.set_unit_decision({
    "unitId": "unit-0002",
    "decision": "accepted",
    "role": "identity-front",
    "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
})
assert state.approval_summary()["readyToPrepare"] is True
digest = state.approval_summary()["proposalDigest"]
approved = state.approve(digest)
assert approved["approval"] == {
    "status": "user-approved", "approvedProposalDigest": digest
}
```

- [ ] **Step 2: Capture exact RED**

Run `python3 -m pytest server/ctv_proposal_test.py -q`; expected missing-module failure.

- [ ] **Step 3: Add caller-owned inspection wrapper**

Expose a narrow `inspect_observation(observation, *, limits=...)` that reuses the
existing internal inspection composition and leaves observation ownership with the
caller. Keep `inspect_source()` behavior byte-compatible.

- [ ] **Step 4: Implement `ProposalState` minimally**

Use ordinary trusted frozen/internal values. Validate every browser-facing mapping
at method entry. Build O(1) maps for units/sources/participants; cap records by the
existing 10,000-unit/row bounds. Read only the selected roster worksheet from its
bounded observation snapshot, after existing workbook safety inspection. Use
OpenPyXL read-only/data-only access over in-memory bytes and examine at most
100,000 cells/10,000 rows/256 characters.

Canonical digest JSON uses sorted keys and compact separators. Rebuild the digest
from current trusted state when approving and compare with `hmac.compare_digest`.

- [ ] **Step 5: Run Task 1 gates**

```bash
python3 -m pytest server/ctv_proposal_test.py server/ctv_inspection_test.py server/ctv_inspection_workbook_test.py -q
python3 -m py_compile server/ctv_proposal.py server/ctv_inspection.py
git diff --check
```

- [ ] **Step 6: Commit and review once**

Commit only the four files as `feat(ctv): build local proposal state`. Independent review must apply the lean threat boundary and focus on API mappings, normal correctness, privacy, limits, source ownership, and no writes—not hostile internal object mutation.

---

### Task 2: Ephemeral Hybrid Review Screen

**Files:**
- Create: `server/ctv_proposal_review.py`
- Create: `server/ctv_proposal_review_test.py`
- Create: `server/ctv_proposal_review_ui.py`
- Create: `server/ctv_proposal_review_ui_test.py`
- Modify: `server/ctv_inspection_media.py`
- Modify: `server/ctv_inspection_media_test.py`
- Modify: `server/ctv_inspection_workbook.py`
- Modify: `server/ctv_inspection_workbook_test.py`

**Interfaces:**
- Consumes: live `ProposalState` and retained observation; existing bounded PDF/image/workbook helpers.
- Produces: `run_local_review(state, *, browser_open=webbrowser.open, clock=time.monotonic) -> dict`; deterministic `UI_HTML`, `UI_CSS`, `UI_JS`; bounded unit preview helpers.

- [ ] **Step 1: Write preview RED tests**

Test generated PDF page, image, and worksheet preview; exact current unit ID;
150-DPI/existing pixel/25-MiB media bounds; worksheet 200x50x256 bound; fixed
errors; no path/temp/write/non-loopback behavior. Reuse existing parser proofs and
do not introduce a second safety framework.

- [ ] **Step 2: Write UI RED tests**

Require the selected C layout: left participant/source navigation, center preview,
right assignment controls, progress/unresolved status, roster selection,
draft/cancel, summary/digest, and disabled approval until ready. Require no CDN,
remote URL, eval, data-driven `innerHTML`, inline event attributes, or private
fixture value.

- [ ] **Step 3: Write HTTP/lifecycle RED tests**

Use real `127.0.0.1` ephemeral sockets with generated/fake state. Cover:

- one-time bootstrap, clean redirect, HttpOnly SameSite=Strict cookie, CSRF;
- exact Host/Origin/method/content-type/route/query/body/key/type/enum/ID checks;
- duplicate JSON key and extra key rejection; 1-MiB request cap;
- self-only CSP and no-store/no-referrer/nosniff/frame-deny headers;
- fixed routes only—no file/upload/proxy/template/WebSocket fallback;
- preview authentication/body caps;
- cancel/draft/summary/approve/heartbeat routing;
- browser failure, idle/total timeout, disconnect, terminal shutdown, and no
  request/token/path/private logging;
- no non-loopback connect/bind and no filesystem writes.

- [ ] **Step 4: Capture exact RED**

Run both new test files; expected missing modules.

- [ ] **Step 5: Implement preview helpers and static UI**

Extract narrow snapshot-byte preview helpers from existing media/workbook modules.
Serve CSS/JS separately under `'self'` CSP. JS uses `textContent` and fixed DOM
construction. All mutations send the CSRF token and exact JSON.

- [ ] **Step 6: Implement the loopback server**

Bind `HTTPServer(("127.0.0.1", 0), Handler)`. Generate `token_urlsafe(32)` bootstrap/session/CSRF values. Disable default logs. Use fixed route dispatch and strict parsers. Stop and clear server/session tokens on every terminal result. Return only state methods' public dicts.

- [ ] **Step 7: Run Task 2 gates**

```bash
python3 -m pytest \
  server/ctv_proposal_review_test.py \
  server/ctv_proposal_review_ui_test.py \
  server/ctv_proposal_test.py \
  server/ctv_inspection_media_test.py \
  server/ctv_inspection_workbook_test.py -q
python3 -m py_compile server/ctv_proposal_review.py server/ctv_proposal_review_ui.py
git diff --check
```

- [ ] **Step 8: Commit and review once**

Commit only the eight files as `feat(ctv): serve local proposal review`. Independent review focuses on real HTTP authorization/input validation, lifecycle, privacy, bounds, no writes/network, UI behavior, and normal state use.

---

### Task 3: CLI Handoff and End-to-End Acceptance

**Files:**
- Modify: `server/ctv_cli_protocol.py`
- Modify: `server/ctv_cli_protocol_test.py`
- Modify: `server/ctv_intake_cli.py`
- Modify: `server/ctv_intake_cli_test.py`
- Modify: `server/README.md`
- Create: `server/ctv_proposal_acceptance_test.py`

**Interfaces:**
- Consumes: one retained observation, `ProposalState`, and `run_local_review`.
- Produces: exact `proposal.review` CLI envelope and documented WP-local-tool flow.

- [ ] **Step 1: Write exact argv/protocol RED tests**

Test valid exact order plus missing/reordered/duplicated/abbreviated/empty/
option-like/extra tokens; invalid invocation has empty stdout and fixed stderr.
Require lazy imports so existing/invalid commands do not load proposal/browser
modules.

- [ ] **Step 2: Write generated acceptance RED tests**

Use generated roster/PDF/image sources and inject a deterministic local-review
driver. Cover approved/draft/cancelled/failure, canonical bounded JSON, no private
values, no partial result after source mutation, no writes, unchanged source tree,
server cleanup, and legacy command compatibility.

- [ ] **Step 3: Capture exact RED**

Run the new CLI/acceptance selections and require failure because the command is
not integrated.

- [ ] **Step 4: Implement CLI lifecycle**

Add operation `proposal.review`, exact parser/argv matcher, lazy imports, retained
observation + inspection + state + local review composition, fixed controlled
error mapping, 16-MiB canonical emitter, and BaseException containment. Buffer and
emit only after observation close/revalidation.

- [ ] **Step 5: Document WP handoff**

Document preflights, exact command, local browser behavior, privacy boundary,
outcomes/exits, two-hour/five-minute limits, fresh retry, and that WP bundles no
CTV code and no package/payment approval is produced.

- [ ] **Step 6: Run full gates**

```bash
python3 -m pytest -q
npm test -- --run
npm run build
python3 -m py_compile server/ctv_*.py
git diff --check
```

Run one real generated browser smoke: launch the screen, select roster, make
individual and shared/case/exclusion decisions, show summary, approve, verify
canonical CLI JSON, zero browser console errors, server shutdown, no external
network, and byte-for-byte unchanged source tree. Record only sanitized counts.

- [ ] **Step 7: Commit and final review**

Commit the six files as `feat(ctv): expose proposal review command`. Run one
whole-feature review against the lean spec, allow one final correction wave if
needed, then one end-to-end acceptance rerun. Do not recursively harden excluded
same-process attacks.

---

## Completion boundary

When all three tasks are independently accepted and exact-head gates are green,
present local merge, push/PR, or keep-as-is options. Do not prepare a package,
merge, push, release, or clean the worktree without the user's explicit choice.

