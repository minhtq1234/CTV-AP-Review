# AP Review Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a throwaway clickable prototype where an ACC reviewer sees each claimed AP value with the merged document auto-focusing on where the AI found it, and approves or rejects — spending attention only on the flagged fields.

**Architecture:** Single-page Vite + React + TS app, no backend. Seeded `Case[]` data carries typed request-form values (expected) plus seeded AI predictions (value, page, bbox in natural px, confidence). Two pure, unit-tested modules — `verdict` (expected-vs-extracted → one of four verdicts + exception-first ordering) and `loupe` (the reference product's pan/zoom-to-box math) — are isolated from React so they'd graduate to a real app unchanged. Documents are generated crisp SVG page files loaded via `<img>`, with field boxes authored in the same natural-pixel coordinate space.

**Tech Stack:** Vite, React 18, TypeScript, Vitest (pure-logic unit tests). Tabler icons via CDN-less inline where needed; styling with plain CSS mirroring the approved mockup.

**Spec:** [`docs/superpowers/specs/2026-07-08-ap-review-prototype-design.md`](../specs/2026-07-08-ap-review-prototype-design.md)

---

## Testing strategy (read before starting)

- **Pure logic (`verdict.ts`, `loupe.ts`) is built strictly TDD** — failing test first, then minimal code. These are the crown jewels and the parts that graduate; they get thorough coverage.
- **Seed data** gets a small integrity test (each case produces its intended verdict spread).
- **UI components are verified by running the app** (`npm run dev` + the Claude_Preview MCP or a browser), not unit tests. This is a throwaway click-through; component test infrastructure would be over-investment. Each UI task lists concrete "run and observe" checks.

## File structure

```
/                         (repo root = the Vite app)
├── index.html            entry HTML
├── package.json          scripts + deps
├── tsconfig.json         TS config
├── vite.config.ts        Vite + Vitest config
├── public/docs/          generated document images (SVG loaded via <img>)
│   ├── case1-form.svg  case1-receipt.svg
│   ├── case2-form.svg  case2-receipt.svg  case2-photo.svg
│   └── case3-form.svg  case3-receipt.svg
├── src/
│   ├── main.tsx          React entry
│   ├── styles.css        global styles (mirrors mockup)
│   ├── types.ts          Case/CaseField/Prediction/DocPage/Verdict/FieldKind/Frame/Bbox
│   ├── logic/
│   │   ├── verdict.ts        compareField + orderFields (pure)
│   │   ├── verdict.test.ts
│   │   ├── loupe.ts          loupeFrame + boxToViewport (pure)
│   │   └── loupe.test.ts
│   ├── data/
│   │   ├── cases.ts          seeded Case[]
│   │   └── cases.test.ts     integrity test
│   └── components/
│       ├── App.tsx           case switcher + holds case state
│       ├── ReviewScreen.tsx  orchestrator: selection, keyboard, viewport, panes
│       ├── FieldsPanel.tsx   left: summary + ordered rows + chips
│       ├── DocViewer.tsx     right: image + box overlay + auto-focus + toolbar
│       ├── FieldPalette.tsx  ⌘K jump-to-field modal
│       └── ActionBar.tsx     reject (optional reason) + approve + status
```

**Component prop contracts** (lock these; every UI task must match them):

```ts
// App: no props. useState<Case[]>(seedCases); useState<string>(selectedCaseId).
// ReviewScreen
interface ReviewScreenProps { case_: Case; onUpdateCase: (c: Case) => void }
// FieldsPanel
interface FieldsPanelProps { ranked: RankedField[]; selectedKey: string; onSelect: (key: string) => void }
// DocViewer
interface DocViewerProps { pages: DocPage[]; page: number; focusBbox: Bbox | null;
  lockView: boolean; onPageChange: (p: number) => void; onToggleLock: () => void }
// FieldPalette
interface FieldPaletteProps { open: boolean; ranked: RankedField[]; onJump: (key: string) => void; onClose: () => void }
// ActionBar
interface ActionBarProps { status: CaseStatus; onApprove: () => void; onReject: (reason: string) => void }
```

---

## Task 1: Scaffold the Vite + React + TS app

**Files:**
- Create: `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `src/main.tsx`, `src/styles.css`, `src/components/App.tsx`

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "ap-review-prototype",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.2",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 2: Create `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create `vite.config.ts`** (also configures Vitest so `npm test` works)

```ts
/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
```

- [ ] **Step 4: Create `index.html`**

```html
<!doctype html>
<html lang="vi">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Duyệt đề nghị thanh toán — AP Review</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create `src/main.tsx`**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './components/App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 6: Create a placeholder `src/components/App.tsx`**

```tsx
export default function App() {
  return <div style={{ padding: 24 }}>AP Review prototype — scaffold OK</div>
}
```

- [ ] **Step 7: Create minimal `src/styles.css`**

```css
:root { --bg: #f7f6f3; --surface: #ffffff; --border: #e5e3dd; --text: #2b2a28;
  --text-muted: #6b6a66; --danger: #c0392b; --warning: #b9770e; --success: #2e7d46;
  --accent: #2f6db3; --mat: #d3d1c7; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: var(--text); background: var(--bg); }
```

- [ ] **Step 8: Install deps and verify dev server + test runner**

Run: `npm install`
Then run: `npm run build`
Expected: TypeScript compiles and Vite produces `dist/` with no errors.
Then run: `npm test`
Expected: Vitest runs and reports "No test files found" (exit 0) — the runner works.

- [ ] **Step 9: Add a `.gitignore` and commit**

Create `.gitignore`:
```
node_modules
dist
*.local
```

```bash
git add package.json tsconfig.json vite.config.ts index.html src/ .gitignore
git commit -m "chore: scaffold Vite + React + TS app with Vitest"
```

---

## Task 2: Domain types

**Files:**
- Create: `src/types.ts`

- [ ] **Step 1: Write `src/types.ts`**

```ts
export type Verdict = 'match' | 'fuzzy' | 'mismatch' | 'low_conf'
export type FieldKind = 'number' | 'date' | 'text' | 'name'
export type CaseStatus = 'pending' | 'approved' | 'rejected'

export interface Bbox { x: number; y: number; width: number; height: number }

export interface Prediction {
  value: string
  page: number            // 0-based page index
  bbox: Bbox              // natural pixels
  confidence: number      // 0..1
}

export interface CaseField {
  key: string
  label: string           // Vietnamese label
  kind: FieldKind
  expected: string        // typed request-form value
  prediction: Prediction | null
}

export interface DocPage { src: string; width: number; height: number; label?: string }

export interface Case {
  id: string
  title: string
  requester: string
  category: string
  status: CaseStatus
  pages: DocPage[]
  fields: CaseField[]
}

export interface Frame { scale: number; tx: number; ty: number }
```

- [ ] **Step 2: Typecheck and commit**

Run: `npx tsc -b`
Expected: no errors.

```bash
git add src/types.ts
git commit -m "feat: add domain types (Case, CaseField, Prediction, Verdict)"
```

---

## Task 3: Verdict logic (TDD)

**Files:**
- Create: `src/logic/verdict.ts`, `src/logic/verdict.test.ts`

- [ ] **Step 1: Write the failing tests** — `src/logic/verdict.test.ts`

```ts
import { describe, it, expect } from 'vitest'
import { compareField, orderFields } from './verdict'
import type { CaseField, Prediction } from '../types'

const pred = (value: string, confidence = 0.98): Prediction => ({
  value, confidence, page: 0, bbox: { x: 0, y: 0, width: 10, height: 10 },
})

describe('compareField', () => {
  it('numbers: exact numeric equality is a match despite formatting', () => {
    expect(compareField('2.050.000 ₫', pred('2050000'), 'number')).toBe('match')
  })
  it('numbers: different amounts mismatch', () => {
    expect(compareField('2.500.000 ₫', pred('2.050.000'), 'number')).toBe('mismatch')
  })
  it('dates: same day in different formats matches', () => {
    expect(compareField('05/07/2026', pred('2026-07-05'), 'date')).toBe('match')
  })
  it('dates: different day mismatches', () => {
    expect(compareField('05/07/2026', pred('06/07/2026'), 'date')).toBe('mismatch')
  })
  it('text: trimmed exact equality matches, else mismatch', () => {
    expect(compareField('AA/26E-0451', pred(' AA/26E-0451 '), 'text')).toBe('match')
    expect(compareField('AA/26E-0451', pred('AA/26E-0999'), 'text')).toBe('mismatch')
  })
  it('names: identical → match; normalized-close → fuzzy; different → mismatch', () => {
    expect(compareField('Grab', pred('Grab'), 'name')).toBe('match')
    expect(compareField('Grab', pred('CÔNG TY TNHH GRAB'), 'name')).toBe('fuzzy')
    expect(compareField('Grab', pred('Highlands Coffee'), 'name')).toBe('mismatch')
  })
  it('low confidence overlays a match', () => {
    expect(compareField('2050000', pred('2050000', 0.5), 'number')).toBe('low_conf')
  })
  it('mismatch beats low confidence (more severe wins)', () => {
    expect(compareField('2500000', pred('2050000', 0.5), 'number')).toBe('mismatch')
  })
  it('null prediction is a mismatch', () => {
    expect(compareField('2050000', null, 'number')).toBe('mismatch')
  })
})

describe('orderFields', () => {
  const f = (key: string, kind: CaseField['kind'], expected: string, p: Prediction | null): CaseField =>
    ({ key, label: key, kind, expected, prediction: p })

  it('orders mismatch → low_conf → fuzzy → match, keeping original index', () => {
    const fields: CaseField[] = [
      f('ok', 'number', '100', pred('100')),                          // match
      f('vendor', 'name', 'Grab', pred('CÔNG TY TNHH GRAB')),         // fuzzy
      f('inv', 'text', 'X', pred('X', 0.5)),                          // low_conf
      f('total', 'number', '2500000', pred('2050000')),               // mismatch
    ]
    const ranked = orderFields(fields)
    expect(ranked.map(r => r.field.key)).toEqual(['total', 'inv', 'vendor', 'ok'])
    expect(ranked.map(r => r.verdict)).toEqual(['mismatch', 'low_conf', 'fuzzy', 'match'])
    expect(ranked.find(r => r.field.key === 'total')!.index).toBe(3)  // original index preserved
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/logic/verdict.test.ts`
Expected: FAIL — `compareField`/`orderFields` not exported.

- [ ] **Step 3: Implement `src/logic/verdict.ts`**

```ts
import type { CaseField, FieldKind, Prediction, Verdict } from '../types'

export const LOW_CONF = 0.7      // below this confidence → ⚠
export const NAME_SIM = 0.8      // name similarity ≥ this (and not exact) → ~ fuzzy

const digits = (s: string) => s.replace(/[^\d]/g, '')

function normNumber(s: string): string { return String(parseInt(digits(s) || 'NaN', 10)) }

function normDate(s: string): string {
  const t = s.trim()
  let m = t.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/)          // YYYY-MM-DD
  if (m) return `${+m[3]}-${+m[2]}-${+m[1]}`
  m = t.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/)              // DD/MM/YYYY
  if (m) return `${+m[1]}-${+m[2]}-${+m[3]}`
  return t
}

function stripDiacritics(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D')
}

function normName(s: string): string {
  return stripDiacritics(s.toLowerCase())
    .replace(/\b(cong ty|cty|tnhh|cp|co\.?|ltd|jsc)\b/g, ' ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length
  const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)])
  for (let j = 0; j <= n; j++) d[0][j] = j
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
  return d[m][n]
}

function similarity(a: string, b: string): number {
  if (!a && !b) return 1
  const longer = Math.max(a.length, b.length)
  if (longer === 0) return 1
  // token-containment boost: "grab" fully inside "cong ty tnhh grab" should score high
  const at = a.split(' '), bt = b.split(' ')
  const contained = at.every(t => bt.includes(t)) || bt.every(t => at.includes(t))
  const lev = 1 - levenshtein(a, b) / longer
  return contained ? Math.max(lev, 0.9) : lev
}

function baseVerdict(expected: string, value: string, kind: FieldKind): Verdict {
  switch (kind) {
    case 'number': return normNumber(expected) === normNumber(value) ? 'match' : 'mismatch'
    case 'date':   return normDate(expected) === normDate(value) ? 'match' : 'mismatch'
    case 'text':   return expected.trim() === value.trim() ? 'match' : 'mismatch'
    case 'name': {
      if (expected.trim() === value.trim()) return 'match'
      const sim = similarity(normName(expected), normName(value))
      return sim >= NAME_SIM ? 'fuzzy' : 'mismatch'
    }
  }
}

export function compareField(expected: string, prediction: Prediction | null, kind: FieldKind): Verdict {
  if (!prediction) return 'mismatch'
  const base = baseVerdict(expected, prediction.value, kind)
  if (base === 'mismatch') return 'mismatch'                    // most severe wins
  if (prediction.confidence < LOW_CONF) return 'low_conf'
  return base                                                   // 'match' or 'fuzzy'
}

const SEVERITY: Record<Verdict, number> = { mismatch: 0, low_conf: 1, fuzzy: 2, match: 3 }

export interface RankedField { field: CaseField; index: number; verdict: Verdict }

export function orderFields(fields: CaseField[]): RankedField[] {
  return fields
    .map((field, index) => ({ field, index, verdict: compareField(field.expected, field.prediction, field.kind) }))
    .sort((a, b) => {
      if (SEVERITY[a.verdict] !== SEVERITY[b.verdict]) return SEVERITY[a.verdict] - SEVERITY[b.verdict]
      const pa = a.field.prediction, pb = b.field.prediction
      const paPage = pa ? pa.page : Infinity, pbPage = pb ? pb.page : Infinity
      if (paPage !== pbPage) return paPage - pbPage
      const ay = pa ? pa.bbox.y : Infinity, by = pb ? pb.bbox.y : Infinity
      return ay - by
    })
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/logic/verdict.test.ts`
Expected: PASS (all cases green).

- [ ] **Step 5: Commit**

```bash
git add src/logic/verdict.ts src/logic/verdict.test.ts
git commit -m "feat: verdict logic — compareField + exception-first ordering (TDD)"
```

---

## Task 4: Loupe (auto-focus) math (TDD)

**Files:**
- Create: `src/logic/loupe.ts`, `src/logic/loupe.test.ts`

- [ ] **Step 1: Write the failing tests** — `src/logic/loupe.test.ts`

```ts
import { describe, it, expect } from 'vitest'
import { loupeFrame, boxToViewport } from './loupe'

const nat = { w: 800, h: 1120 }
const vp = { w: 500, h: 600 }

describe('loupeFrame', () => {
  it('with no box, fits the whole page centered at 0.92 scale', () => {
    const f = loupeFrame(null, nat, vp)
    const expected = Math.min(vp.w / nat.w, vp.h / nat.h) * 0.92
    expect(f.scale).toBeCloseTo(expected, 5)
    expect(f.tx).toBeCloseTo((vp.w - nat.w * f.scale) / 2, 5)
    expect(f.ty).toBeCloseTo((vp.h - nat.h * f.scale) / 2, 5)
  })
  it('centers a small box in the viewport', () => {
    const bbox = { x: 600, y: 900, width: 120, height: 28 }
    const f = loupeFrame(bbox, nat, vp)
    const cx = bbox.x + bbox.width / 2, cy = bbox.y + bbox.height / 2
    expect(f.tx + cx * f.scale).toBeCloseTo(vp.w / 2, 4)
    expect(f.ty + cy * f.scale).toBeCloseTo(vp.h / 2, 4)
  })
  it('clamps magnification to [1.1, 2.5]', () => {
    const tiny = { x: 10, y: 10, width: 4, height: 4 }
    expect(loupeFrame(tiny, nat, vp).scale).toBeLessThanOrEqual(2.5)
    const big = { x: 0, y: 0, width: 800, height: 1120 }
    expect(loupeFrame(big, nat, vp).scale).toBeLessThanOrEqual(Math.min(vp.w / 800, vp.h / 1120) * 0.92 + 1e-9)
  })
  it('returns identity for zero-size natural image', () => {
    expect(loupeFrame(null, { w: 0, h: 0 }, vp)).toEqual({ scale: 1, tx: 0, ty: 0 })
  })
})

describe('boxToViewport', () => {
  it('maps a natural-px box into viewport coords under a frame', () => {
    const r = boxToViewport({ x: 100, y: 50, width: 40, height: 20 }, { scale: 2, tx: 10, ty: 5 })
    expect(r).toEqual({ left: 210, top: 105, width: 80, height: 40 })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/logic/loupe.test.ts`
Expected: FAIL — module not found / not exported.

- [ ] **Step 3: Implement `src/logic/loupe.ts`** (ported verbatim from the reference `fields.ts`)

```ts
import type { Bbox, Frame } from '../types'

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export function loupeFrame(
  bbox: Bbox | null,
  nat: { w: number; h: number },
  vp: { w: number; h: number },
): Frame {
  if (nat.w === 0 || nat.h === 0) return { scale: 1, tx: 0, ty: 0 }
  if (!bbox) {
    const s = Math.min(vp.w / nat.w, vp.h / nat.h) * 0.92
    return { scale: s, tx: (vp.w - nat.w * s) / 2, ty: (vp.h - nat.h * s) / 2 }
  }
  const targetH = vp.h * 0.14
  const magnify = clamp(targetH / bbox.height, 1.1, 2.5)
  const fit = Math.min(vp.w / bbox.width, vp.h / bbox.height) * 0.92
  const s = Math.min(magnify, fit)
  const cx = bbox.x + bbox.width / 2
  const cy = bbox.y + bbox.height / 2
  return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
}

export function boxToViewport(bbox: Bbox, frame: Frame) {
  return {
    left: frame.tx + bbox.x * frame.scale,
    top: frame.ty + bbox.y * frame.scale,
    width: bbox.width * frame.scale,
    height: bbox.height * frame.scale,
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/logic/loupe.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/logic/loupe.ts src/logic/loupe.test.ts
git commit -m "feat: loupe auto-focus math ported from reference (TDD)"
```

---

## Task 5: Generate document images (SVG pages)

Generated SVG pages loaded via `<img>`. Every page uses natural size **800 × 1120**. Receipts share one **coordinate grid** so field boxes are predictable. Boxes below are the exact `bbox` values reused by Task 6.

**Shared receipt grid** (used by every `*-receipt.svg` and `case2-photo.svg`):

| Field (row) | Value baseline `y` | Value box `{x, y, width, height}` |
|---|---|---|
| Vendor name (title) | 120 | `{ x: 210, y: 96, width: 380, height: 40 }` |
| Invoice no. | 210 | `{ x: 470, y: 192, width: 210, height: 30 }` |
| Invoice date | 250 | `{ x: 470, y: 232, width: 150, height: 30 }` |
| Subtotal (Tiền hàng) | 560 | `{ x: 520, y: 542, width: 190, height: 32 }` |
| VAT (Thuế GTGT) | 610 | `{ x: 520, y: 592, width: 190, height: 32 }` |
| Total (Tổng cộng) | 680 | `{ x: 500, y: 658, width: 210, height: 40 }` |

**Files (Create):** `public/docs/case1-form.svg`, `case1-receipt.svg`, `case2-form.svg`, `case2-receipt.svg`, `case2-photo.svg`, `case3-form.svg`, `case3-receipt.svg`

- [ ] **Step 1: Create the receipt template — write `public/docs/case2-receipt.svg`** (the hero; other receipts are the same geometry with different text/boxed row)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1120" viewBox="0 0 800 1120" font-family="monospace">
  <rect width="800" height="1120" fill="#ffffff"/>
  <rect x="60" y="40" width="680" height="1040" fill="none" stroke="#e5e3dd"/>
  <text x="400" y="120" font-size="30" font-weight="bold" text-anchor="middle" fill="#2b2a28">CÔNG TY TNHH GRAB</text>
  <text x="400" y="150" font-size="15" text-anchor="middle" fill="#777">Dịch vụ di chuyển • MST 0312345678</text>
  <line x1="90" y1="170" x2="710" y2="170" stroke="#ccc" stroke-dasharray="4 4"/>
  <text x="120" y="210" font-size="18" fill="#444">Số hóa đơn:</text>
  <text x="470" y="210" font-size="18" fill="#2b2a28">AA/26E-0451</text>
  <text x="120" y="250" font-size="18" fill="#444">Ngày:</text>
  <text x="470" y="250" font-size="18" fill="#2b2a28">05/07/2026</text>
  <line x1="90" y1="290" x2="710" y2="290" stroke="#ccc" stroke-dasharray="4 4"/>
  <text x="120" y="360" font-size="18" fill="#2b2a28">Cước di chuyển (x3 chuyến)</text>
  <text x="120" y="560" font-size="18" fill="#444">Tiền hàng</text>
  <text x="700" y="560" font-size="18" text-anchor="end" fill="#2b2a28">1.863.636</text>
  <text x="120" y="610" font-size="18" fill="#444">Thuế GTGT (10%)</text>
  <text x="700" y="610" font-size="18" text-anchor="end" fill="#2b2a28">186.364</text>
  <line x1="90" y1="635" x2="710" y2="635" stroke="#999"/>
  <text x="120" y="685" font-size="24" font-weight="bold" fill="#2b2a28">TỔNG CỘNG</text>
  <text x="700" y="685" font-size="24" font-weight="bold" text-anchor="end" fill="#2b2a28">2.050.000 ₫</text>
  <text x="400" y="1040" font-size="13" text-anchor="middle" fill="#999">Cảm ơn quý khách</text>
</svg>
```

- [ ] **Step 2: Write the request-form template — `public/docs/case2-form.svg`** (page 1 of the merged doc; no boxes needed — it's the typed request)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1120" viewBox="0 0 800 1120" font-family="sans-serif">
  <rect width="800" height="1120" fill="#ffffff"/>
  <text x="400" y="90" font-size="26" font-weight="bold" text-anchor="middle" fill="#2b2a28">ĐỀ NGHỊ THANH TOÁN</text>
  <text x="400" y="122" font-size="15" text-anchor="middle" fill="#777">Mã: PR-2026-0142</text>
  <line x1="60" y1="150" x2="740" y2="150" stroke="#e5e3dd"/>
  <text x="80" y="210" font-size="18" fill="#444">Người đề nghị:</text><text x="320" y="210" font-size="18" fill="#2b2a28">Nguyễn Văn A</text>
  <text x="80" y="255" font-size="18" fill="#444">Hạng mục:</text><text x="320" y="255" font-size="18" fill="#2b2a28">Chi phí đi lại</text>
  <text x="80" y="300" font-size="18" fill="#444">Nhà cung cấp:</text><text x="320" y="300" font-size="18" fill="#2b2a28">Grab</text>
  <text x="80" y="345" font-size="18" fill="#444">Số hóa đơn:</text><text x="320" y="345" font-size="18" fill="#2b2a28">AA/26E-0451</text>
  <text x="80" y="390" font-size="18" fill="#444">Ngày hóa đơn:</text><text x="320" y="390" font-size="18" fill="#2b2a28">05/07/2026</text>
  <text x="80" y="435" font-size="18" fill="#444">Tiền hàng:</text><text x="320" y="435" font-size="18" fill="#2b2a28">1.863.636 ₫</text>
  <text x="80" y="480" font-size="18" fill="#444">Thuế GTGT:</text><text x="320" y="480" font-size="18" fill="#2b2a28">186.364 ₫</text>
  <text x="80" y="525" font-size="18" fill="#444">Tổng cộng:</text><text x="320" y="525" font-size="18" font-weight="bold" fill="#2b2a28">2.500.000 ₫</text>
</svg>
```

- [ ] **Step 3: Write the remaining SVGs** using the same two templates, changing only the noted text:

`public/docs/case1-form.svg` — form template with: requester `Trần Thị B`, category `Tiếp khách`, vendor `Highlands`, invoice `HD-2026-8842`, date `03/07/2026`, subtotal `454.545 ₫`, VAT `45.455 ₫`, total `500.000 ₫`, code `PR-2026-0138`, title stays.

`public/docs/case1-receipt.svg` — receipt template with title `CÔNG TY CP HIGHLANDS COFFEE`, invoice `HD-2026-8842`, date `03/07/2026`, subtotal `454.545`, VAT `45.455`, total `500.000 ₫`.

`public/docs/case2-photo.svg` — a "photo of a boarding-pass / trip summary" page: receipt template but title `GRAB - CHI TIẾT CHUYẾN ĐI`, invoice line replaced with `Mã chuyến: G-88213`, total line `TỔNG: 2.050.000 ₫`. (Extra page to exercise multi-page nav; no field boxes point here.)

`public/docs/case3-form.svg` — form template with requester `Lê Văn C`, category `Văn phòng phẩm`, vendor `Nhà sách Fahasa`, invoice `FHS-0099`, date `01/07/2026`, subtotal `290.909 ₫`, VAT `29.091 ₫`, total `320.000 ₫`, code `PR-2026-0151`.

`public/docs/case3-receipt.svg` — receipt template but styled "handwritten/crumpled": add `transform="rotate(-1 400 560)"` on a `<g>` wrapping the text, title `NHÀ SÁCH FAHASA`, invoice `FHS-0099`, date `01/07/2026`, subtotal `290.909`, VAT `29.091`, total `320.000 ₫`, and a faint `<rect ... fill="#00000008"/>` smudge over the total to motivate low confidence.

- [ ] **Step 4: Verify the images render**

Run: `npm run dev`, then open `http://localhost:5173/docs/case2-receipt.svg` and `.../case2-form.svg` in a browser (or the Claude_Preview MCP).
Expected: each SVG renders as a clean page at 800×1120; the receipt total reads `2.050.000 ₫`, the form total reads `2.500.000 ₫`.

- [ ] **Step 5: Commit**

```bash
git add public/docs/
git commit -m "feat: generated Vietnamese/VND document pages (SVG) for 3 cases"
```

---

## Task 6: Seed case data

**Files:**
- Create: `src/data/cases.ts`, `src/data/cases.test.ts`

Boxes use the shared receipt grid from Task 5. Confidence values are chosen to produce the intended verdict per the spec.

- [ ] **Step 1: Write the integrity test — `src/data/cases.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { seedCases } from './cases'
import { orderFields } from '../logic/verdict'

const verdictsFor = (id: string) => {
  const c = seedCases.find(x => x.id === id)!
  return orderFields(c.fields).map(r => r.verdict)
}

describe('seed cases', () => {
  it('has three cases, all pending', () => {
    expect(seedCases.map(c => c.id)).toEqual(['PR-2026-0138', 'PR-2026-0142', 'PR-2026-0151'])
    expect(seedCases.every(c => c.status === 'pending')).toBe(true)
  })
  it('case 1 is clean: no mismatch, no low_conf (matches + one fuzzy vendor)', () => {
    const v = verdictsFor('PR-2026-0138')
    expect(v).not.toContain('mismatch')
    expect(v).not.toContain('low_conf')
    expect(v).toContain('fuzzy')
  })
  it('case 2 has exactly one mismatch (total) and one low_conf (invoice no.)', () => {
    const v = verdictsFor('PR-2026-0142')
    expect(v.filter(x => x === 'mismatch')).toHaveLength(1)
    expect(v.filter(x => x === 'low_conf')).toHaveLength(1)
  })
  it('case 3 has a low_conf but no mismatch (amount matches, AI unsure)', () => {
    const v = verdictsFor('PR-2026-0151')
    expect(v).toContain('low_conf')
    expect(v).not.toContain('mismatch')
  })
  it('every prediction bbox falls inside its page bounds', () => {
    for (const c of seedCases)
      for (const f of c.fields)
        if (f.prediction) {
          const pg = c.pages[f.prediction.page]
          const b = f.prediction.bbox
          expect(b.x + b.width).toBeLessThanOrEqual(pg.width)
          expect(b.y + b.height).toBeLessThanOrEqual(pg.height)
        }
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/data/cases.test.ts`
Expected: FAIL — `seedCases` not found.

- [ ] **Step 3: Implement `src/data/cases.ts`**

```ts
import type { Bbox, Case } from '../types'

const RECEIPT = { width: 800, height: 1120 }
const box = (b: Bbox) => b

// shared receipt grid (Task 5)
const G = {
  vendor:   { x: 210, y: 96,  width: 380, height: 40 },
  invoice:  { x: 470, y: 192, width: 210, height: 30 },
  date:     { x: 470, y: 232, width: 150, height: 30 },
  subtotal: { x: 520, y: 542, width: 190, height: 32 },
  vat:      { x: 520, y: 592, width: 190, height: 32 },
  total:    { x: 500, y: 658, width: 210, height: 40 },
}

export const seedCases: Case[] = [
  {
    id: 'PR-2026-0138', title: 'Tiếp khách phòng Kinh doanh', requester: 'Trần Thị B',
    category: 'Tiếp khách', status: 'pending',
    pages: [
      { src: '/docs/case1-form.svg', ...RECEIPT, label: 'Đề nghị' },
      { src: '/docs/case1-receipt.svg', ...RECEIPT, label: 'Hóa đơn' },
    ],
    fields: [
      { key: 'vendor', label: 'Nhà cung cấp', kind: 'name', expected: 'Highlands',
        prediction: { value: 'CÔNG TY CP HIGHLANDS COFFEE', page: 1, bbox: box(G.vendor), confidence: 0.95 } },
      { key: 'invoice', label: 'Số hóa đơn', kind: 'text', expected: 'HD-2026-8842',
        prediction: { value: 'HD-2026-8842', page: 1, bbox: box(G.invoice), confidence: 0.97 } },
      { key: 'date', label: 'Ngày hóa đơn', kind: 'date', expected: '03/07/2026',
        prediction: { value: '03/07/2026', page: 1, bbox: box(G.date), confidence: 0.98 } },
      { key: 'subtotal', label: 'Tiền hàng', kind: 'number', expected: '454.545 ₫',
        prediction: { value: '454.545', page: 1, bbox: box(G.subtotal), confidence: 0.96 } },
      { key: 'vat', label: 'Thuế GTGT', kind: 'number', expected: '45.455 ₫',
        prediction: { value: '45.455', page: 1, bbox: box(G.vat), confidence: 0.96 } },
      { key: 'total', label: 'Tổng cộng', kind: 'number', expected: '500.000 ₫',
        prediction: { value: '500.000', page: 1, bbox: box(G.total), confidence: 0.98 } },
    ],
  },
  {
    id: 'PR-2026-0142', title: 'Chi phí đi lại — đón đối tác', requester: 'Nguyễn Văn A',
    category: 'Chi phí đi lại', status: 'pending',
    pages: [
      { src: '/docs/case2-form.svg', ...RECEIPT, label: 'Đề nghị' },
      { src: '/docs/case2-receipt.svg', ...RECEIPT, label: 'Hóa đơn' },
      { src: '/docs/case2-photo.svg', ...RECEIPT, label: 'Ảnh chuyến đi' },
    ],
    fields: [
      { key: 'vendor', label: 'Nhà cung cấp', kind: 'name', expected: 'Grab',
        prediction: { value: 'CÔNG TY TNHH GRAB', page: 1, bbox: box(G.vendor), confidence: 0.94 } },
      { key: 'invoice', label: 'Số hóa đơn', kind: 'text', expected: 'AA/26E-0451',
        prediction: { value: 'AA/26E-0451', page: 1, bbox: box(G.invoice), confidence: 0.52 } },
      { key: 'date', label: 'Ngày hóa đơn', kind: 'date', expected: '05/07/2026',
        prediction: { value: '05/07/2026', page: 1, bbox: box(G.date), confidence: 0.99 } },
      { key: 'subtotal', label: 'Tiền hàng', kind: 'number', expected: '1.863.636 ₫',
        prediction: { value: '1.863.636', page: 1, bbox: box(G.subtotal), confidence: 0.97 } },
      { key: 'vat', label: 'Thuế GTGT', kind: 'number', expected: '186.364 ₫',
        prediction: { value: '186.364', page: 1, bbox: box(G.vat), confidence: 0.97 } },
      { key: 'total', label: 'Tổng cộng', kind: 'number', expected: '2.500.000 ₫',
        prediction: { value: '2.050.000', page: 1, bbox: box(G.total), confidence: 0.98 } },
    ],
  },
  {
    id: 'PR-2026-0151', title: 'Văn phòng phẩm quý 3', requester: 'Lê Văn C',
    category: 'Văn phòng phẩm', status: 'pending',
    pages: [
      { src: '/docs/case3-form.svg', ...RECEIPT, label: 'Đề nghị' },
      { src: '/docs/case3-receipt.svg', ...RECEIPT, label: 'Hóa đơn' },
    ],
    fields: [
      { key: 'vendor', label: 'Nhà cung cấp', kind: 'name', expected: 'Nhà sách Fahasa',
        prediction: { value: 'NHÀ SÁCH FAHASA', page: 1, bbox: box(G.vendor), confidence: 0.9 } },
      { key: 'invoice', label: 'Số hóa đơn', kind: 'text', expected: 'FHS-0099',
        prediction: { value: 'FHS-0099', page: 1, bbox: box(G.invoice), confidence: 0.88 } },
      { key: 'date', label: 'Ngày hóa đơn', kind: 'date', expected: '01/07/2026',
        prediction: { value: '01/07/2026', page: 1, bbox: box(G.date), confidence: 0.86 } },
      { key: 'subtotal', label: 'Tiền hàng', kind: 'number', expected: '290.909 ₫',
        prediction: { value: '290.909', page: 1, bbox: box(G.subtotal), confidence: 0.83 } },
      { key: 'vat', label: 'Thuế GTGT', kind: 'number', expected: '29.091 ₫',
        prediction: { value: '29.091', page: 1, bbox: box(G.vat), confidence: 0.8 } },
      { key: 'total', label: 'Tổng cộng', kind: 'number', expected: '320.000 ₫',
        prediction: { value: '320.000', page: 1, bbox: box(G.total), confidence: 0.5 } },
    ],
  },
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/data/cases.test.ts`
Expected: PASS. (If case 1 vendor comes back `match` not `fuzzy`, the value is being treated as identical — confirm the expected/extracted differ; if case 3 total shows `mismatch`, recheck the numbers are equal.)

- [ ] **Step 5: Commit**

```bash
git add src/data/cases.ts src/data/cases.test.ts
git commit -m "feat: seed 3 AP cases (clean, mismatch, low-confidence)"
```

---

## Task 7: Walking skeleton — App shell + two-pane ReviewScreen

Goal: a runnable end-to-end screen. Case switcher, header, a raw document image on the right, a plain (unstyled, unordered) field list on the left with click + ↑/↓ selection. No chips/auto-focus yet — those land in Tasks 8–9.

**Files:**
- Modify: `src/components/App.tsx`
- Create: `src/components/ReviewScreen.tsx`

- [ ] **Step 1: Implement `src/components/App.tsx`**

```tsx
import { useState } from 'react'
import type { Case } from '../types'
import { seedCases } from '../data/cases'
import ReviewScreen from './ReviewScreen'

export default function App() {
  const [cases, setCases] = useState<Case[]>(seedCases)
  const [selectedId, setSelectedId] = useState(cases[0].id)
  const current = cases.find(c => c.id === selectedId)!
  const updateCase = (c: Case) => setCases(prev => prev.map(x => (x.id === c.id ? c : x)))

  return (
    <div className="app">
      <nav className="case-tabs">
        {cases.map(c => (
          <button key={c.id} className={c.id === selectedId ? 'tab active' : 'tab'}
            onClick={() => setSelectedId(c.id)}>
            {c.id} · {c.category}
            {c.status !== 'pending' && <span className={`dot ${c.status}`} />}
          </button>
        ))}
      </nav>
      <ReviewScreen key={current.id} case_={current} onUpdateCase={updateCase} />
    </div>
  )
}
```

- [ ] **Step 2: Implement a minimal `src/components/ReviewScreen.tsx`** (skeleton — selection + page state; panes filled in later tasks)

```tsx
import { useEffect, useState } from 'react'
import type { Case } from '../types'
import { orderFields } from '../logic/verdict'

interface ReviewScreenProps { case_: Case; onUpdateCase: (c: Case) => void }

export default function ReviewScreen({ case_ }: ReviewScreenProps) {
  const ranked = orderFields(case_.fields)
  const [selectedKey, setSelectedKey] = useState(ranked[0]?.field.key ?? '')
  const [page, setPage] = useState(0)

  const selected = case_.fields.find(f => f.key === selectedKey) ?? null

  useEffect(() => {
    if (selected?.prediction) setPage(selected.prediction.page)
  }, [selectedKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      e.preventDefault()
      const i = ranked.findIndex(r => r.field.key === selectedKey)
      const next = e.key === 'ArrowDown' ? Math.min(i + 1, ranked.length - 1) : Math.max(i - 1, 0)
      setSelectedKey(ranked[next].field.key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ranked, selectedKey])

  return (
    <div className="screen">
      <header className="screen-head">
        <div><strong>Đề nghị thanh toán #{case_.id}</strong> — {case_.requester} · {case_.category}</div>
      </header>
      <div className="panes">
        <aside className="fields-pane">
          {ranked.map(r => (
            <div key={r.field.key}
              className={r.field.key === selectedKey ? 'frow sel' : 'frow'}
              onClick={() => setSelectedKey(r.field.key)}>
              {r.field.label}: {r.field.expected} → {r.field.prediction?.value ?? '—'} [{r.verdict}]
            </div>
          ))}
        </aside>
        <section className="doc-pane">
          <img src={case_.pages[page].src} alt="" style={{ maxWidth: '100%' }} />
        </section>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add skeleton layout CSS to `src/styles.css`**

```css
.app { height: 100vh; display: flex; flex-direction: column; }
.case-tabs { display: flex; gap: 8px; padding: 10px 14px; border-bottom: 0.5px solid var(--border); background: var(--surface); }
.tab { padding: 6px 12px; border: 0.5px solid var(--border); border-radius: 8px; background: transparent; cursor: pointer; }
.tab.active { border-color: var(--accent); color: var(--accent); }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-left: 6px; }
.dot.approved { background: var(--success); } .dot.rejected { background: var(--danger); }
.screen { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.screen-head { padding: 11px 15px; border-bottom: 0.5px solid var(--border); background: var(--surface); font-size: 14px; }
.panes { flex: 1; display: flex; min-height: 0; }
.fields-pane { width: 47%; overflow-y: auto; border-right: 0.5px solid var(--border); background: var(--surface); }
.doc-pane { width: 53%; position: relative; overflow: hidden; background: var(--mat); display: flex; align-items: center; justify-content: center; }
.frow { padding: 10px 12px; border-bottom: 0.5px solid var(--border); cursor: pointer; font-size: 13px; }
.frow.sel { background: #eaf1fb; }
```

- [ ] **Step 4: Run the app and verify the skeleton**

Run: `npm run dev` and open the app (Claude_Preview MCP or browser at `http://localhost:5173`).
Expected: three case tabs; clicking a tab switches cases; clicking a field row highlights it and the right pane shows that field's page; `↑`/`↓` move the selection through the exception-first order (Case 2 starts on `Tổng cộng` = mismatch).

- [ ] **Step 5: Commit**

```bash
git add src/components/App.tsx src/components/ReviewScreen.tsx src/styles.css
git commit -m "feat: walking-skeleton review screen (case switch, selection, keyboard nav)"
```

---

## Task 8: DocViewer — auto-focus, box overlay, zoom toolbar

Replace the raw `<img>` with a real viewer: measures its own viewport, computes the frame via `loupeFrame`, applies a `translate/scale` transform, draws the highlight rect via `boxToViewport`, has a page indicator + zoom toolbar (fit / − / % / + / spotlight-lock).

**Files:**
- Create: `src/components/DocViewer.tsx`
- Modify: `src/components/ReviewScreen.tsx` (use DocViewer), `src/styles.css`

- [ ] **Step 1: Implement `src/components/DocViewer.tsx`**

```tsx
import { useLayoutEffect, useRef, useState } from 'react'
import type { Bbox, DocPage, Frame } from '../types'
import { boxToViewport, loupeFrame } from '../logic/loupe'

interface DocViewerProps {
  pages: DocPage[]; page: number; focusBbox: Bbox | null
  lockView: boolean; onPageChange: (p: number) => void; onToggleLock: () => void
}

export default function DocViewer({ pages, page, focusBbox, lockView, onPageChange, onToggleLock }: DocViewerProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [vp, setVp] = useState({ w: 0, h: 0 })
  const [frame, setFrame] = useState<Frame>({ scale: 1, tx: 0, ty: 0 })
  const nat = { w: pages[page].width, h: pages[page].height }

  useLayoutEffect(() => {
    const el = ref.current!
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useLayoutEffect(() => {
    if (lockView || vp.w === 0) return
    setFrame(loupeFrame(focusBbox, nat, vp))
  }, [focusBbox, vp.w, vp.h, page, lockView])

  const zoom = (factor: number) => setFrame(f => {
    const s = Math.max(0.1, Math.min(6, f.scale * factor))
    const cx = (vp.w / 2 - f.tx) / f.scale, cy = (vp.h / 2 - f.ty) / f.scale
    return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
  })
  const fit = () => setFrame(loupeFrame(null, nat, vp))

  const hl = focusBbox ? boxToViewport(focusBbox, frame) : null

  return (
    <section className="doc-pane" ref={ref}>
      <div className="doc-page" style={{ transform: `translate(${frame.tx}px, ${frame.ty}px) scale(${frame.scale})` }}>
        <img src={pages[page].src} width={nat.w} height={nat.h} alt="" />
      </div>
      {hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}

      <div className="doc-badge">Trang {page + 1} / {pages.length}{pages[page].label ? ` · ${pages[page].label}` : ''}</div>

      <div className="doc-nav">
        <button disabled={page === 0} onClick={() => onPageChange(page - 1)} aria-label="Trang trước">‹</button>
        <button disabled={page === pages.length - 1} onClick={() => onPageChange(page + 1)} aria-label="Trang sau">›</button>
      </div>

      <div className="doc-tools">
        <button onClick={fit} aria-label="Vừa khung">⤢</button>
        <button onClick={() => zoom(0.8)} aria-label="Thu nhỏ">−</button>
        <span>{Math.round(frame.scale * 100)}%</span>
        <button onClick={() => zoom(1.25)} aria-label="Phóng to">+</button>
        <button className={lockView ? 'on' : ''} onClick={onToggleLock} aria-label="Khoá khung nhìn">🔒</button>
      </div>
    </section>
  )
}
```

- [ ] **Step 2: Wire DocViewer into `ReviewScreen.tsx`**

Add state `const [lockView, setLockView] = useState(false)` and replace the `<section className="doc-pane">…</section>` block with:

```tsx
<DocViewer
  pages={case_.pages}
  page={page}
  focusBbox={selected?.prediction && selected.prediction.page === page ? selected.prediction.bbox : null}
  lockView={lockView}
  onPageChange={setPage}
  onToggleLock={() => setLockView(v => !v)}
/>
```

Add `import DocViewer from './DocViewer'` at the top. Remove the old inline `.doc-pane`/`<img>` markup.

- [ ] **Step 3: Add viewer CSS to `src/styles.css`**

```css
.doc-page { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
.doc-page img { display: block; }
.doc-hl { position: absolute; border: 2px solid var(--danger); border-radius: 3px;
  background: rgba(192,57,43,0.10); pointer-events: none; }
.doc-badge { position: absolute; top: 10px; right: 10px; font-size: 11px; background: var(--surface);
  border: 0.5px solid var(--border); color: var(--text-muted); padding: 3px 8px; border-radius: 8px; }
.doc-nav { position: absolute; top: 50%; width: 100%; display: flex; justify-content: space-between;
  transform: translateY(-50%); pointer-events: none; }
.doc-nav button { pointer-events: auto; margin: 0 6px; width: 30px; height: 30px; border-radius: 50%;
  border: 0.5px solid var(--border); background: var(--surface); cursor: pointer; }
.doc-nav button:disabled { opacity: 0.3; cursor: default; }
.doc-tools { position: absolute; bottom: 10px; left: 10px; display: flex; align-items: center; gap: 2px;
  background: var(--surface); border: 0.5px solid var(--border); border-radius: 8px; padding: 2px 4px; font-size: 12px; }
.doc-tools button { border: 0; background: transparent; cursor: pointer; padding: 4px 6px; border-radius: 5px; }
.doc-tools button.on { background: #eaf1fb; }
```

- [ ] **Step 4: Run and verify auto-focus**

Run: `npm run dev`. In Case 2, select `Tổng cộng` → the receipt (page 2) pans/zooms so the total is centered with a red highlight box on it. Select `Số hóa đơn` → focus jumps to the invoice-no region. Toggle 🔒 then select another field → view stays put. `+`/`−`/`⤢` change zoom.

- [ ] **Step 5: Commit**

```bash
git add src/components/DocViewer.tsx src/components/ReviewScreen.tsx src/styles.css
git commit -m "feat: DocViewer with loupe auto-focus, box overlay, zoom toolbar"
```

---

## Task 9: FieldsPanel — verdict chips, summary, expected→actual

Replace the plain skeleton list with the designed panel: a summary line with counts, and rows showing a verdict chip, label, `expected → actual` (actual in red when mismatch), and confidence (amber when low).

**Files:**
- Create: `src/components/FieldsPanel.tsx`
- Modify: `src/components/ReviewScreen.tsx`, `src/styles.css`

- [ ] **Step 1: Implement `src/components/FieldsPanel.tsx`**

```tsx
import type { Verdict } from '../types'
import type { RankedField } from '../logic/verdict'

interface FieldsPanelProps { ranked: RankedField[]; selectedKey: string; onSelect: (key: string) => void }

const CHIP: Record<Verdict, { cls: string; glyph: string }> = {
  mismatch: { cls: 'v-mismatch', glyph: '✗' },
  low_conf: { cls: 'v-low', glyph: '!' },
  fuzzy: { cls: 'v-fuzzy', glyph: '~' },
  match: { cls: 'v-match', glyph: '✓' },
}

export default function FieldsPanel({ ranked, selectedKey, onSelect }: FieldsPanelProps) {
  const n = (v: Verdict) => ranked.filter(r => r.verdict === v).length
  return (
    <aside className="fields-pane">
      <div className="fields-summary">
        <span>{ranked.length} trường</span>
        {n('mismatch') > 0 && <span className="s-mismatch">● {n('mismatch')} lệch</span>}
        {n('low_conf') > 0 && <span className="s-low">● {n('low_conf')} tin cậy thấp</span>}
      </div>
      {ranked.map(r => {
        const c = CHIP[r.verdict]
        const actual = r.field.prediction?.value ?? '—'
        const conf = r.field.prediction ? Math.round(r.field.prediction.confidence * 100) : null
        return (
          <div key={r.field.key} className={`frow ${r.field.key === selectedKey ? 'sel' : ''}`}
            onClick={() => onSelect(r.field.key)}>
            <span className={`chip ${c.cls}`}>{c.glyph}</span>
            <span className="fbody">
              <span className="flabel">{r.field.label}</span>
              <span className="fvals">
                {r.field.expected} → <span className={r.verdict === 'mismatch' ? 'act bad' : 'act'}>{actual}</span>
              </span>
            </span>
            {conf !== null && <span className={`conf ${r.verdict === 'low_conf' ? 'low' : ''}`}>{conf}%</span>}
          </div>
        )
      })}
    </aside>
  )
}
```

- [ ] **Step 2: Use FieldsPanel in `ReviewScreen.tsx`**

Replace the `<aside className="fields-pane">…</aside>` skeleton block with:

```tsx
<FieldsPanel ranked={ranked} selectedKey={selectedKey} onSelect={setSelectedKey} />
```

Add `import FieldsPanel from './FieldsPanel'`. Delete the now-unused `.frow` skeleton markup (CSS stays, extended below).

- [ ] **Step 3: Extend `src/styles.css`**

```css
.fields-summary { display: flex; gap: 12px; align-items: center; font-size: 12px; color: var(--text-muted);
  padding: 9px 13px; border-bottom: 0.5px solid var(--border); }
.s-mismatch { color: var(--danger); } .s-low { color: var(--warning); }
.frow { display: flex; gap: 10px; align-items: flex-start; padding: 9px 12px; border-bottom: 0.5px solid var(--border); cursor: pointer; }
.frow.sel { background: #eaf1fb; }
.chip { width: 22px; height: 22px; border-radius: 6px; display: flex; align-items: center; justify-content: center;
  font-size: 12px; flex: 0 0 auto; }
.v-mismatch { background: #fbeaea; color: var(--danger); }
.v-low { background: #fbf1e0; color: var(--warning); }
.v-fuzzy { background: #f1efe8; color: var(--text-muted); border: 0.5px solid var(--border); }
.v-match { background: #e7f3ea; color: var(--success); }
.fbody { min-width: 0; display: flex; flex-direction: column; }
.flabel { font-size: 13px; font-weight: 500; }
.fvals { font-size: 12px; color: var(--text-muted); font-family: monospace; }
.act { color: var(--text); } .act.bad { color: var(--danger); font-weight: 500; }
.conf { margin-left: auto; font-size: 11px; color: var(--text-muted); padding-top: 2px; }
.conf.low { color: var(--warning); }
```

- [ ] **Step 4: Run and verify**

Run: `npm run dev`. Case 2 left panel shows: `✗ Tổng cộng 2.500.000 ₫ → 2.050.000 ₫` (red) at top, then `! Số hóa đơn … 52%` (amber), then `~ Nhà cung cấp`, then the green `✓` rows. Summary reads `6 trường · 1 lệch · 1 tin cậy thấp`. Case 1 shows all green + one `~`. Clicking a row still drives auto-focus.

- [ ] **Step 5: Commit**

```bash
git add src/components/FieldsPanel.tsx src/components/ReviewScreen.tsx src/styles.css
git commit -m "feat: FieldsPanel with verdict chips, summary, expected/actual"
```

---

## Task 10: FieldPalette — ⌘K jump-to-field

**Files:**
- Create: `src/components/FieldPalette.tsx`
- Modify: `src/components/ReviewScreen.tsx`, `src/styles.css`

- [ ] **Step 1: Implement `src/components/FieldPalette.tsx`**

```tsx
import { useEffect, useState } from 'react'
import type { RankedField } from '../logic/verdict'

interface FieldPaletteProps { open: boolean; ranked: RankedField[]; onJump: (key: string) => void; onClose: () => void }

export default function FieldPalette({ open, ranked, onJump, onClose }: FieldPaletteProps) {
  const [q, setQ] = useState('')
  useEffect(() => { if (open) setQ('') }, [open])
  if (!open) return null
  const rows = ranked.filter(r => r.field.label.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette" onClick={e => e.stopPropagation()}>
        <input autoFocus placeholder="Nhảy tới trường…" value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') onClose()
            if (e.key === 'Enter' && rows[0]) { onJump(rows[0].field.key); onClose() }
          }} />
        <div className="palette-list">
          {rows.map(r => (
            <div key={r.field.key} className="palette-row"
              onClick={() => { onJump(r.field.key); onClose() }}>
              <span className={`chip v-${r.verdict === 'low_conf' ? 'low' : r.verdict}`} />
              {r.field.label}
              <span className="palette-val">{r.field.prediction?.value ?? '—'}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire ⌘K into `ReviewScreen.tsx`**

Add `const [paletteOpen, setPaletteOpen] = useState(false)`. In the keydown handler add, before the arrow handling:

```tsx
if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen(true); return }
```

Render before `</div>` of `.screen`:

```tsx
<FieldPalette open={paletteOpen} ranked={ranked}
  onJump={setSelectedKey} onClose={() => setPaletteOpen(false)} />
```

Add `import FieldPalette from './FieldPalette'`.

- [ ] **Step 3: Add palette CSS to `src/styles.css`**

```css
.palette-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,0.25); display: flex; justify-content: center; align-items: flex-start; padding-top: 12vh; z-index: 20; }
.palette { width: 420px; max-width: 90%; background: var(--surface); border: 0.5px solid var(--border); border-radius: 12px; overflow: hidden; }
.palette input { width: 100%; border: 0; border-bottom: 0.5px solid var(--border); padding: 12px 14px; font-size: 14px; outline: none; }
.palette-list { max-height: 300px; overflow-y: auto; }
.palette-row { display: flex; align-items: center; gap: 10px; padding: 9px 14px; cursor: pointer; font-size: 13px; }
.palette-row:hover { background: #f4f3ef; }
.palette-row .chip { width: 10px; height: 10px; border-radius: 50%; }
.palette-val { margin-left: auto; color: var(--text-muted); font-family: monospace; font-size: 12px; }
```

Note: `.screen` must be `position: relative` for the backdrop to fill it — add that to the existing `.screen` rule.

- [ ] **Step 4: Run and verify**

Run: `npm run dev`. Press `⌘K` (or `Ctrl+K`) → palette opens focused; typing `tổng` filters to Tổng cộng; Enter or click jumps selection (and auto-focuses the doc); Esc closes.

- [ ] **Step 5: Commit**

```bash
git add src/components/FieldPalette.tsx src/components/ReviewScreen.tsx src/styles.css
git commit -m "feat: ⌘K jump-to-field palette"
```

---

## Task 11: ActionBar — approve / reject with optional reason

**Files:**
- Create: `src/components/ActionBar.tsx`
- Modify: `src/components/ReviewScreen.tsx`, `src/styles.css`

- [ ] **Step 1: Implement `src/components/ActionBar.tsx`**

```tsx
import { useState } from 'react'
import type { CaseStatus } from '../types'

interface ActionBarProps { status: CaseStatus; onApprove: () => void; onReject: (reason: string) => void }

export default function ActionBar({ status, onApprove, onReject }: ActionBarProps) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  if (status !== 'pending') {
    return (
      <div className="action-bar">
        <span className={`final ${status}`}>
          {status === 'approved' ? '✓ Đã phê duyệt' : '✗ Đã từ chối'}
        </span>
      </div>
    )
  }

  return (
    <div className="action-bar">
      <span className="hint">↑ ↓ chuyển trường · ⌘K nhảy nhanh</span>
      <div className="actions">
        {rejecting && (
          <input className="reason" autoFocus placeholder="Lý do (tuỳ chọn)"
            value={reason} onChange={e => setReason(e.target.value)} />
        )}
        <button className="btn" onClick={() => (rejecting ? onReject(reason) : setRejecting(true))}>✗ Từ chối</button>
        <button className="btn primary" onClick={onApprove}>✓ Phê duyệt</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire into `ReviewScreen.tsx`**

Add below `.panes` (inside `.screen`):

```tsx
<ActionBar
  status={case_.status}
  onApprove={() => onUpdateCase({ ...case_, status: 'approved' })}
  onReject={(reason) => onUpdateCase({ ...case_, status: 'rejected' })}
/>
```

Note the plan intentionally does not persist the reject reason anywhere (throwaway mock; terminal action). Add `import ActionBar from './ActionBar'`. `onUpdateCase` is already a prop; keep it destructured in the signature: `export default function ReviewScreen({ case_, onUpdateCase }: ReviewScreenProps)`.

- [ ] **Step 3: Add action-bar CSS to `src/styles.css`**

```css
.action-bar { display: flex; align-items: center; justify-content: space-between; padding: 11px 15px;
  border-top: 0.5px solid var(--border); background: var(--surface); }
.action-bar .hint { font-size: 12px; color: var(--text-muted); }
.actions { display: flex; gap: 9px; align-items: center; margin-left: auto; }
.reason { border: 0.5px solid var(--border); border-radius: 8px; padding: 7px 10px; font-size: 13px; width: 220px; }
.btn { border: 0.5px solid var(--border); background: transparent; padding: 7px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; }
.btn.primary { border-color: var(--accent); background: #eaf1fb; color: var(--accent); font-weight: 500; }
.final { font-size: 14px; font-weight: 500; margin-left: auto; }
.final.approved { color: var(--success); } .final.rejected { color: var(--danger); }
```

- [ ] **Step 4: Run and verify**

Run: `npm run dev`. Approve → bar collapses to `✓ Đã phê duyệt` and the tab shows a green dot. Reject → shows an optional reason field, clicking again confirms → `✗ Đã từ chối` + red dot. Switching tabs preserves each case's status (state lives in App).

- [ ] **Step 5: Commit**

```bash
git add src/components/ActionBar.tsx src/components/ReviewScreen.tsx src/styles.css
git commit -m "feat: approve/reject action bar with terminal status"
```

---

## Task 12: Polish pass + full verification

**Files:**
- Modify: `src/styles.css`, any component needing alignment with the mockup

- [ ] **Step 1: Visual polish against the approved mockup**

Compare the running app to the mockup and tighten: header layout + status pill (`Chờ duyệt` amber), spacing/typography of rows, the mat color, the highlight box, toolbar. Adjust `src/styles.css` values to match. Keep it a single focused CSS pass — no new features.

- [ ] **Step 2: Full click-through verification (use the Claude_Preview MCP)**

Walk all three cases and confirm:
- Case 1 (clean): all rows green + one `~`; approving works.
- Case 2 (mismatch): `✗ Tổng cộng` top, `!` invoice-no, `~` vendor, greens below; clicking each auto-focuses the right region; page nav (‹ ›) moves across the 3 pages; reject-with-reason works.
- Case 3 (low-confidence): `! Tổng cộng` at top (amount matches but confidence 50%); auto-focus lands on the total; approving works.
- `⌘K` and `↑/↓` work in every case; 🔒 lock holds the view.

- [ ] **Step 3: Run the full test suite and typecheck/build**

Run: `npm test`
Expected: all `verdict`, `loupe`, and `cases` tests PASS.
Run: `npm run build`
Expected: typecheck + Vite build succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "polish: align review screen with approved mockup + final verification"
```

---

## Self-review (completed by plan author)

- **Spec coverage:** layout (T7–9), auto-focus/loupe (T4, T8), keyboard + ⌘K (T7, T10), four-verdict model + ordering (T3, T9), no-gate approve/reject + optional reason (T11), case schema (T2, T6), three seed cases (T6), generated VND/Vietnamese docs with natural-px boxes (T5), pure-logic isolation (T3, T4). All spec sections map to tasks.
- **Placeholders:** none — every code step carries full content; the one deferred item (reject reason not persisted) is an explicit design choice, noted at its step.
- **Type consistency:** `compareField(expected, prediction, kind)`, `orderFields → RankedField{field,index,verdict}`, `loupeFrame(bbox,nat,vp)`, `boxToViewport`, and the six component prop interfaces are used identically across tasks.
