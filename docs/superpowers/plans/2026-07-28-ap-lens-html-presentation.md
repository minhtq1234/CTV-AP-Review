# AP Lens HTML Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, standalone five-slide Vietnamese HTML presentation that explains the CTV AP Review workflow to reviewers and stakeholders.

**Architecture:** A single offline HTML file owns the deck markup, embedded CSS illustrations, and dependency-free navigation script. A small Node built-in test defines the content, privacy, offline, and interaction contract before the deck exists; browser QA then verifies the rendered interaction and responsive behavior.

**Tech Stack:** HTML5, embedded CSS, inline SVG, vanilla JavaScript, Node.js `node:test`, browser Fullscreen API.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`; do not touch v2.
- Create exactly five 16:9 slides in Vietnamese.
- Use the approved title `AP Lens — Soát hồ sơ CTV thông minh`.
- Create one standalone deliverable at `docs/presentations/ctv-ap-review-overview.html`.
- Do not add runtime dependencies, remote assets, backend endpoints, application routes, or production component changes.
- Use only synthetic, PII-free names, identifiers, document labels, and values.
- Preserve every existing v1 behavior and the frontend/backend ports 5174/8001.
- Do not push unless the user explicitly requests it after completion.

---

## File Structure

- Create `scripts/presentation.test.mjs`: Node built-in structural, content, privacy, and offline contract for the deck.
- Create `docs/presentations/ctv-ap-review-overview.html`: complete standalone presentation, styles, illustrations, and navigation.
- Modify `package.json`: add the focused `test:presentation` command.

### Task 1: Define the presentation contract with a failing test

**Files:**
- Create: `scripts/presentation.test.mjs`
- Modify: `package.json`
- Test: `scripts/presentation.test.mjs`

**Interfaces:**
- Consumes: Node.js built-ins `node:test`, `node:assert/strict`, and `node:fs`.
- Produces: `npm run test:presentation`, which validates the exact deck path and approved content contract.

- [ ] **Step 1: Add the focused test command**

Add this script to `package.json` without changing existing scripts:

```json
"test:presentation": "node --test scripts/presentation.test.mjs"
```

- [ ] **Step 2: Write the failing structural and content tests**

Create `scripts/presentation.test.mjs` with:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const deckPath = new URL(
  '../docs/presentations/ctv-ap-review-overview.html',
  import.meta.url,
)

const readDeck = () => readFileSync(deckPath, 'utf8')

test('contains exactly five slides and the approved story', () => {
  const html = readDeck()
  assert.equal((html.match(/class="slide(?:\s[^"]*)?"/g) ?? []).length, 5)
  for (const requiredText of [
    'AP Lens — Soát hồ sơ CTV thông minh',
    'Tải lên một lần, hệ thống chuẩn bị phần còn lại',
    'Một dashboard cho toàn bộ đợt hồ sơ',
    'Xem tổng quan, rồi kiểm tra từng trường',
    'Tập trung vào ngoại lệ, xuất kết quả rõ ràng',
    'Chưa xem',
    'Đang xem',
    'Đã xong',
    'Flagged',
    'Cần chú ý trước',
    'Tổng quan',
    'Từ chối hồ sơ',
    'Xuất báo cáo',
  ]) {
    assert.match(html, new RegExp(requiredText))
  }
})

test('is offline, dependency-free, and PII-safe by construction', () => {
  const html = readDeck()
  assert.doesNotMatch(html, /(?:src|href)=["']https?:\/\//i)
  assert.doesNotMatch(html, /<script[^>]+src=/i)
  assert.doesNotMatch(html, /<link[^>]+rel=["']stylesheet/i)
  assert.doesNotMatch(html, /\b\d{12}\b/)
  assert.doesNotMatch(html, /Tôn Trung Quốc Đạt|Kiều Kiến Thịnh|Nguyễn Thúy Vy/i)
})

test('includes accessible navigation, fullscreen, keyboard, and touch controls', () => {
  const html = readDeck()
  assert.match(html, /aria-label="Trang trước"/)
  assert.match(html, /aria-label="Trang tiếp theo"/)
  assert.match(html, /aria-label="Toàn màn hình"/)
  assert.match(html, /requestFullscreen/)
  assert.match(html, /ArrowLeft/)
  assert.match(html, /ArrowRight/)
  assert.match(html, /PageUp/)
  assert.match(html, /PageDown/)
  assert.match(html, /touchstart/)
  assert.match(html, /prefers-reduced-motion/)
})
```

- [ ] **Step 3: Run the focused test and observe the required failure**

Run:

```bash
npm run test:presentation
```

Expected: FAIL with `ENOENT` because
`docs/presentations/ctv-ap-review-overview.html` does not exist yet.

- [ ] **Step 4: Commit the red test**

```bash
git add package.json scripts/presentation.test.mjs
git commit -m "test: define AP Lens presentation contract"
```

### Task 2: Build the standalone five-slide deck

**Files:**
- Create: `docs/presentations/ctv-ap-review-overview.html`
- Test: `scripts/presentation.test.mjs`

**Interfaces:**
- Consumes: the text and interaction contract enforced by `npm run test:presentation`.
- Produces: one directly openable HTML file with `goToSlide(index: number)`, `nextSlide()`, and `previousSlide()` internal navigation functions.

- [ ] **Step 1: Create semantic deck markup**

Create a complete HTML document containing:

```html
<main class="deck" aria-label="AP Lens — Soát hồ sơ CTV thông minh">
  <section class="slide is-active" data-slide="0">…Slide 1…</section>
  <section class="slide" data-slide="1" aria-hidden="true">…Slide 2…</section>
  <section class="slide" data-slide="2" aria-hidden="true">…Slide 3…</section>
  <section class="slide" data-slide="3" aria-hidden="true">…Slide 4…</section>
  <section class="slide" data-slide="4" aria-hidden="true">…Slide 5…</section>
</main>
```

Every slide must use the approved title and copy from the design spec. Add
schematic UI elements for inputs/pipeline, packet statuses, the split reviewer,
and report output. Use only generic labels such as `CTV 01`, `Gói 08`, and
masked values such as `•••• 4821`; never include a full 12-digit identifier.

- [ ] **Step 2: Add the embedded visual system**

Inside `<style>`, define:

```css
:root {
  --navy-950: #07142b;
  --navy-900: #0b1f3a;
  --blue-500: #2f7cf6;
  --cyan-300: #70d7ff;
  --surface: #f8fbff;
  --ink: #10213a;
  --muted: #61718a;
  --green: #258657;
  --amber: #d99300;
  --rose: #c94162;
}

html, body {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  background: var(--navy-950);
}

.deck {
  width: min(100vw, calc(100vh * 16 / 9));
  aspect-ratio: 16 / 9;
  position: relative;
  margin: auto;
  overflow: hidden;
}

.slide {
  position: absolute;
  inset: 0;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
}

.slide.is-active {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

Extend this base into the approved navy, white-surface, blue-accent visual
language. Use CSS and inline SVG only. Keep status meaning redundant through
text, icons, and color.

- [ ] **Step 3: Add navigation and accessible state updates**

Embed a script with this behavior:

```js
const slides = [...document.querySelectorAll('.slide')]
const dots = [...document.querySelectorAll('[data-slide-target]')]
let currentSlide = 0

function goToSlide(index) {
  currentSlide = Math.max(0, Math.min(slides.length - 1, index))
  slides.forEach((slide, slideIndex) => {
    const active = slideIndex === currentSlide
    slide.classList.toggle('is-active', active)
    slide.setAttribute('aria-hidden', String(!active))
    slide.inert = !active
  })
  dots.forEach((dot, dotIndex) => {
    dot.classList.toggle('is-active', dotIndex === currentSlide)
    dot.setAttribute('aria-current', dotIndex === currentSlide ? 'page' : 'false')
  })
  document.querySelector('[data-position]').textContent =
    `${currentSlide + 1} / ${slides.length}`
}

const nextSlide = () => goToSlide(currentSlide + 1)
const previousSlide = () => goToSlide(currentSlide - 1)
```

Wire buttons, dots, Arrow Left/Right, Page Up/Page Down, Space, Home/End,
fullscreen, and a horizontal touch-swipe threshold of 50 pixels. Prevent Space
from navigating when a button has focus.

- [ ] **Step 4: Run the focused test and make it green**

Run:

```bash
npm run test:presentation
```

Expected: 3 tests pass.

- [ ] **Step 5: Run the existing frontend regression suite and build**

Run:

```bash
npm test
npm run build
```

Expected: all existing frontend tests pass and the production build completes.

- [ ] **Step 6: Commit the standalone deck**

```bash
git add docs/presentations/ctv-ap-review-overview.html
git commit -m "feat: add AP Lens HTML presentation"
```

### Task 3: Perform browser presentation QA

**Files:**
- Verify: `docs/presentations/ctv-ap-review-overview.html`

**Interfaces:**
- Consumes: the completed standalone HTML deck.
- Produces: browser evidence for initial render, navigation, responsiveness, and console health.

- [ ] **Step 1: Serve the standalone file locally for browser inspection**

Run:

```bash
python3 -m http.server 4176 --directory docs/presentations
```

Open:

```text
http://127.0.0.1:4176/ctv-ap-review-overview.html
```

- [ ] **Step 2: Verify interaction and accessibility state**

Confirm:

- Slide 1 loads with `1 / 5`.
- Next, previous, dots, Arrow Left/Right, Page Up/Page Down, Space, Home, and
  End select the expected slide.
- Only the selected slide has `aria-hidden="false"` and is not inert.
- The fullscreen button is visible and invokes the Fullscreen API.
- No slide reveals real names or a full 12-digit number.

- [ ] **Step 3: Verify desktop and narrow layouts**

At 1440×900 and 1024×768 confirm:

- the entire deck canvas fits the viewport;
- headings, diagrams, and navigation remain legible;
- no page-level horizontal or vertical overflow appears; and
- controls remain clickable.

- [ ] **Step 4: Verify the console and direct-file constraint**

Confirm zero console errors over all five slides. Also open the file directly
with a `file://` URL and confirm the first slide and navigation work without a
server or network.

- [ ] **Step 5: Run final verification and inspect the diff**

Run:

```bash
npm run test:presentation
npm test
npm run build
git diff --check
git status --short
```

Expected: all commands pass; the only implementation commits are the red test,
the deck, and any narrowly scoped QA correction.

