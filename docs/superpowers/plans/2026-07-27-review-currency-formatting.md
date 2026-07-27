# Review Currency Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Format Excel roster amounts as Vietnamese đồng in both the reviewer field list and bbox callout without changing raw data or comparison behavior.

**Architecture:** Add a pure presentation helper that formats only `Thanh toán` fields with `kind: number`. Both reviewer display paths consume that helper; manifests, backend responses, review persistence, and comparison inputs remain raw.

**Tech Stack:** TypeScript 5, React 18, Vitest, Vite

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`.
- Keep frontend/backend ports `5174`/`8001`.
- Do not modify the v2 checkout.
- Do not push.
- Format only fields whose group is `Thanh toán` and kind is `number`.
- Preserve raw manifest, backend, comparison, review, report, and persisted values.
- Unparseable values must render unchanged.

---

### Task 1: Pure roster-value presentation formatter

**Files:**
- Create: `src/logic/reviewValue.ts`
- Create: `src/logic/reviewValue.test.ts`

**Interfaces:**
- Consumes: `Pick<CtvField, 'group' | 'kind' | 'expected'>`
- Produces: `formatRosterValue(field): string`

- [ ] **Step 1: Write the failing formatter tests**

Create `src/logic/reviewValue.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { CtvField } from '../ctv/types'
import * as reviewValue from './reviewValue'

const field = (
  expected: string,
  overrides: Partial<Pick<CtvField, 'group' | 'kind'>> = {},
): Pick<CtvField, 'group' | 'kind' | 'expected'> => ({
  group: 'Thanh toán',
  kind: 'number',
  expected,
  ...overrides,
})

describe('formatRosterValue', () => {
  const formatRosterValue = (
    reviewValue as typeof reviewValue & {
      formatRosterValue?: (
        value: Pick<CtvField, 'group' | 'kind' | 'expected'>,
      ) => string
    }
  ).formatRosterValue

  it('formats raw and already-grouped financial integers as Vietnamese đồng', () => {
    expect(formatRosterValue?.(field('6111111'))).toBe('6.111.111 ₫')
    expect(formatRosterValue?.(field('6.111.111 ₫'))).toBe('6.111.111 ₫')
    expect(formatRosterValue?.(field('6,111,111 VND'))).toBe('6.111.111 ₫')
    expect(formatRosterValue?.(field('0'))).toBe('0 ₫')
  })

  it('leaves non-financial and unparseable values unchanged', () => {
    expect(formatRosterValue?.(field('2865', { group: 'Chứng từ' }))).toBe('2865')
    expect(formatRosterValue?.(field('không rõ'))).toBe('không rõ')
  })
})
```

- [ ] **Step 2: Run the formatter tests to verify RED**

Run:

```bash
npm test -- src/logic/reviewValue.test.ts
```

Expected: FAIL because `formatRosterValue` is undefined.

- [ ] **Step 3: Implement the minimal pure formatter**

Create `src/logic/reviewValue.ts`:

```ts
import type { CtvField } from '../ctv/types'

type ReviewValueField = Pick<CtvField, 'group' | 'kind' | 'expected'>

export function formatRosterValue(field: ReviewValueField): string {
  if (field.group !== 'Thanh toán' || field.kind !== 'number') {
    return field.expected
  }

  const amount = field.expected
    .trim()
    .replace(/\s*(?:₫|VND)\s*$/i, '')
    .replace(/[.,\s]/g, '')

  if (!/^\d+$/.test(amount)) return field.expected
  return `${BigInt(amount).toLocaleString('vi-VN')} ₫`
}
```

- [ ] **Step 4: Simplify the test import and verify GREEN**

Replace the namespace/optional lookup with:

```ts
import { formatRosterValue } from './reviewValue'
```

Remove the local optional `formatRosterValue` declaration, then run:

```bash
npm test -- src/logic/reviewValue.test.ts
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit the pure formatter**

```bash
git add src/logic/reviewValue.ts src/logic/reviewValue.test.ts
git commit -m "feat(review): format roster currency values"
```

---

### Task 2: Use the formatter in both reviewer display paths

**Files:**
- Modify: `src/components/FolderFieldsPanel.tsx`
- Modify: `src/components/FolderReview.tsx`
- Modify: `src/components/reviewPresentation.test.tsx`

**Interfaces:**
- Consumes: `formatRosterValue(field): string` from Task 1
- Produces: identical formatted copy in the Excel row and selected bbox callout

- [ ] **Step 1: Write failing component tests**

In `src/components/reviewPresentation.test.tsx`, import `FolderReview`, then add a financial fixture:

```ts
const financialRow: RankedCtv = {
  field: {
    key: 'phi',
    label: 'Phí dịch vụ',
    group: 'Thanh toán',
    check: 'compare',
    kind: 'number',
    expected: '6111111',
    sources: [{
      docId: 'contract',
      page: 0,
      value: '6.111.111',
      bbox: { x: 100, y: 200, width: 180, height: 30 },
      confidence: 0.9,
    }],
  },
  index: 0,
  verdict: 'match',
  actual: '6.111.111',
  sources: [{
    verdict: 'match',
    source: {
      docId: 'contract',
      page: 0,
      value: '6.111.111',
      bbox: { x: 100, y: 200, width: 180, height: 30 },
      confidence: 0.9,
    },
  }],
}
```

Add a field-panel assertion:

```ts
it('formats a financial Excel value as Vietnamese đồng', () => {
  const html = renderPanel(
    { done: false, fields: {}, rejection: null },
    [financialRow],
  )
  expect(html).toContain('Kê khai (Excel): <b>6.111.111 ₫</b>')
  expect(html).not.toContain('<b>6111111</b>')
})
```

Add an integration assertion using a one-field synthetic folder:

```ts
it('uses the same formatted amount in the field row and bbox callout', () => {
  const field = financialRow.field
  const html = renderToStaticMarkup(
    <FolderReview
      folder={{
        id: 'synthetic',
        name: 'Synthetic CTV',
        product: 'Synthetic Product',
        status: 'pending',
        exempt: false,
        docs: [{
          id: 'contract',
          kind: 'contract',
          label: 'Synthetic contract',
          pages: [{ src: '/synthetic.svg', width: 1000, height: 1400 }],
        }],
        fields: [field],
      }}
      review={{ done: false, fields: {}, rejection: null }}
      onReview={() => undefined}
      onCommitReview={async () => undefined}
    />,
  )
  expect(html.match(/6\.111\.111 ₫/g)).toHaveLength(2)
  expect(html).not.toContain('>6111111<')
})
```

- [ ] **Step 2: Run component tests to verify RED**

Run:

```bash
npm test -- src/components/reviewPresentation.test.tsx
```

Expected: both new tests fail because the row and callout still render `6111111`.

- [ ] **Step 3: Format the field-list value**

In `src/components/FolderFieldsPanel.tsx`, import the helper:

```ts
import { formatRosterValue } from '../logic/reviewValue'
```

Replace the raw expected rendering with:

```tsx
<div className="cfield-exp">
  Kê khai (Excel): <b>{formatRosterValue(r.field)}</b>
</div>
```

- [ ] **Step 4: Format the selected bbox callout value**

In `src/components/FolderReview.tsx`, import:

```ts
import { formatRosterValue } from '../logic/reviewValue'
```

Replace the `rosterValue` prop with:

```tsx
rosterValue={selField ? formatRosterValue(selField) : null}
```

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```bash
npm test -- src/logic/reviewValue.test.ts src/components/reviewPresentation.test.tsx src/components/evidenceViewer.test.tsx
```

Expected: all focused tests pass.

- [ ] **Step 6: Run complete verification**

Run:

```bash
npm test
python3 -m pytest server splitter -q
npm run build
git diff --check
```

Expected:

- all frontend tests pass;
- all 136 backend/splitter tests pass;
- the production build completes;
- `git diff --check` prints no errors.

- [ ] **Step 7: Browser QA**

At `http://127.0.0.1:5174/`, open a packet containing a raw Excel service fee
and verify:

- the left field row displays grouped Vietnamese đồng;
- the blue bbox callout shows the identical formatted value;
- account number, CCCD, tax ID, name, and date rows remain unchanged;
- selecting fields, bbox autofocus, one-page/two-page mode, and pan still work;
- no console errors appear.

- [ ] **Step 8: Commit the display integration**

```bash
git add src/components/FolderFieldsPanel.tsx src/components/FolderReview.tsx src/components/reviewPresentation.test.tsx
git commit -m "feat(review): show formatted service fees"
```
