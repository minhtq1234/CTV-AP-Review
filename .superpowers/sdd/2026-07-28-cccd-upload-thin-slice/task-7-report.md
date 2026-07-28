# Task 7 report — CCCD workbook upload control

## Scope

- Added the optional CCCD `.xlsx` chooser and browser-side roster requirement.
- Added `cccd` multipart forwarding, progress copy, and compact detail types.
- Did not change the backend or the Task 8 case-detail summary UI.

## Strict TDD evidence

1. **Eligibility and progress label** — RED: `npx vitest run
   src/upload/cccd.test.ts src/upload/api.test.ts` failed because `./cccd`
   did not exist and `stageLabel('cccd')` returned `cccd`. GREEN: the same
   command passed 10 tests after adding the pure rule functions and label.
2. **Multipart contract** — RED: `npx vitest run src/upload/api.test.ts
   src/upload/cccd.test.ts` failed because the submitted form had no `cccd`
   entry. GREEN: the same command passed 11 tests after adding the optional
   third argument and append. The legacy PDF-and-roster test verifies no
   `cccd` field is sent by existing callers.
3. **Static upload screen** — RED: `npx vitest run src/upload/api.test.ts
   src/upload/cccd.test.ts src/components/UploadScreen.test.ts` failed because
   the CCCD chooser label was absent. GREEN: the same command passed 13 tests
   after adding the chooser, exact high-resolution guidance, blocking message,
   accessible clear action, and flow forwarding.

## Final verification

- Focused Vitest: 13 passed across API, eligibility, and static screen suites.
- `npm test -- --run`: 65 passed in 11 files.
- `npm run build`: passed (`tsc -b` and Vite production bundle).
- `git diff --check`: clean.

## Self-review

- CCCD without a roster disables submit and renders exactly `Cần bảng kê để tự
  động ghép CCCD.`; PDF is always required and busy state always blocks.
- Clearing CCCD resets both React state and the native file input, restoring
  the legacy roster-optional path.
- The new file input remains inside a label, the validation uses an alert role,
  and clear/submit controls explicitly use `type="button"`.
- `createCase(pdf, roster?)` continues to omit `cccd`; supplied CCCD uses only
  the exact `cccd` multipart key.
- The change is restricted to Task 7 frontend files and this report.

## Commit

- `feat: add CCCD workbook upload control`

## Concern

The browser rule is intentionally UX-only; normal case creation still relies
on the backend as the authoritative cross-field validator. The existing test
stack has no DOM interaction dependency, so the rendered test covers the
chooser/copy/input count while removal behavior is covered by implementation
review and the pure eligibility regression.
