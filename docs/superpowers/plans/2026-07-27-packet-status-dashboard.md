# CTV v1 Packet-Status Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a derived four-state packet dashboard with orthogonal system attention, local filters, stable attention-first ordering, accurate review progress, and automatic return-from-review updates.

**Architecture:** A pure frontend `packetDashboard` module derives lifecycle, attention, counts, filtering, and ordering from `PacketMeta[]`; `CaseDetail` owns only local control state and card rendering. The backend adds a response-only `reviewFieldCount` derived from existing manifests to case-detail and review responses without changing storage or the review request.

**Tech Stack:** React 18, TypeScript 5.5, Vitest 2, FastAPI/Pydantic, Python unittest, Vite 5.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`.
- Do not modify `/Users/lap16603/Documents/New project/work/CTV_APReview`.
- Preserve frontend port `5174` and backend port `8001`.
- Do not add a persisted lifecycle status or change the `PacketReview` write shape.
- Preserve existing layout, packet rejection, case progress, resubmission, and report behavior.
- Use synthetic, PII-free fixtures and do not record real PII in QA evidence.
- Do not push.

---

### Task 1: Response-Only Review Field Count

**Files:**
- Modify: `server/app_test.py`
- Modify: `server/app.py`
- Modify: `src/upload/api.test.ts`
- Modify: `src/upload/api.ts`

**Interfaces:**
- Produces: `PacketMeta.reviewFieldCount: number`
- Produces: backend `_packet_for_response(cid: str, packet: dict) -> dict`
- Preserves: `PUT /api/cases/{cid}/packets/{i}/review` request body

- [ ] **Step 1: Write failing backend tests**

Add endpoint tests using a temporary synthetic case and manifest:

```py
def test_case_and_review_responses_include_manifest_field_count_without_persisting(client, app_store):
    cid = seed_case(app_store, packets=[synthetic_packet(0)])
    packet_dir = Path(app_store.case_dir(cid)) / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text(
        json.dumps({"fields": [{"key": "a"}, {"key": "b"}]}),
        encoding="utf-8",
    )

    detail = client.get(f"/api/cases/{cid}").json()
    assert detail["packets"][0]["reviewFieldCount"] == 2

    updated = client.put(
        f"/api/cases/{cid}/packets/0/review",
        json={"done": False, "fields": {}, "rejection": None},
    ).json()
    assert updated["packet"]["reviewFieldCount"] == 2
    assert "reviewFieldCount" not in app_store.get(cid)["packets"][0]


def test_case_response_uses_zero_field_count_when_manifest_is_missing(client, app_store):
    cid = seed_case(app_store, packets=[synthetic_packet(0)])
    detail = client.get(f"/api/cases/{cid}").json()
    assert detail["packets"][0]["reviewFieldCount"] == 0
```

Adapt the fixture names to the existing `server/app_test.py` helpers rather
than creating parallel application setup.

- [ ] **Step 2: Run backend tests and verify RED**

Run:

```bash
python3 -m unittest server.app_test -v
```

Expected: the new assertions fail because `reviewFieldCount` is absent.

- [ ] **Step 3: Implement response-only backend derivation**

In `server/app.py`, add a defensive manifest counter and response copier:

```py
def _review_field_count(cid: str, index: int) -> int:
    path = os.path.join(
        store.case_dir(cid), "packets", str(index), "manifest.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            fields = json.load(f).get("fields")
        return len(fields) if isinstance(fields, list) else 0
    except (OSError, ValueError, TypeError):
        return 0


def _packet_for_response(cid: str, packet: dict) -> dict:
    return {
        **packet,
        "reviewFieldCount": _review_field_count(cid, packet["index"]),
    }
```

Use copied packets in `get_case`:

```py
out["packets"] = [
    _packet_for_response(cid, packet) for packet in case["packets"]
]
```

Use the same copier for the review response:

```py
return {
    "packet": _packet_for_response(cid, packet),
    "progress": progress_of(updated["packets"]),
    "status": updated["status"],
}
```

Do not pass either copied response packet back to `CaseStore`.

- [ ] **Step 4: Run backend tests and verify GREEN**

Run:

```bash
python3 -m unittest server.app_test -v
```

Expected: all endpoint tests pass.

- [ ] **Step 5: Write failing frontend normalization tests**

In `src/upload/api.test.ts`, add a complete synthetic `CaseDetail` response to
the existing fetch test and assert:

```ts
expect(detail.packets[0].reviewFieldCount).toBe(0)
```

for an old response that omits the property, and:

```ts
expect(detail.packets[0].reviewFieldCount).toBe(6)
```

when the server response includes `reviewFieldCount: 6`.

- [ ] **Step 6: Run frontend API tests and verify RED**

Run:

```bash
npm test -- src/upload/api.test.ts
```

Expected: the fallback assertion fails because packet reads do not normalize
`reviewFieldCount`.

- [ ] **Step 7: Implement frontend type and normalization**

In `src/upload/api.ts`, add:

```ts
reviewFieldCount: number
```

to `PacketMeta`, and centralize packet response normalization:

```ts
function normalizePacketMeta(packet: PacketMeta): PacketMeta {
  return {
    ...packet,
    reviewFieldCount: Number.isFinite(packet.reviewFieldCount)
      ? Math.max(0, packet.reviewFieldCount)
      : 0,
    review: normalizePacketReview(packet.review),
  }
}
```

Use it in both `getCase` and `setReview`. Do not change `setReview`'s request
body.

- [ ] **Step 8: Run focused frontend and backend tests**

Run:

```bash
npm test -- src/upload/api.test.ts
python3 -m unittest server.app_test -v
```

Expected: both commands pass.

- [ ] **Step 9: Commit the read-only response contract**

```bash
git add server/app.py server/app_test.py src/upload/api.ts src/upload/api.test.ts
git commit -m "feat: expose packet review field counts"
```

---

### Task 2: Pure Dashboard Derivation

**Files:**
- Create: `src/logic/packetDashboard.test.ts`
- Create: `src/logic/packetDashboard.ts`
- Modify: `src/logic/review.ts`
- Modify: `src/logic/review.test.ts`
- Modify: `src/components/DemoFlow.tsx`

**Interfaces:**
- Produces: `PacketDashboardStatus`
- Produces: `PACKET_DASHBOARD_LABELS`
- Produces: `packetDashboardStatus(packet)`
- Produces: `packetSeenCount(packet)`, `packetFlagCount(packet)`
- Produces: `attentionReasons(packet)`
- Produces: `packetDashboardCounts(packets)`
- Produces: `filterPackets(packets, filter)`
- Produces: `prioritizeAttention(packets)`
- Preserves: legacy `packetStatus` API as a lifecycle-label compatibility
  wrapper until consumers move to the new type

- [ ] **Step 1: Write failing lifecycle and precedence tests**

Create synthetic `PacketMeta` values with literal expected statuses and assert:

```ts
expect(packetDashboardStatus(packet({ done: false }))).toBe('unseen')
expect(packetDashboardStatus(packet({
  done: false,
  fields: { a: { seen: true, flag: null } },
}))).toBe('reviewing')
expect(packetDashboardStatus(packet({ done: true }))).toBe('completed')
expect(packetDashboardStatus(packet({
  done: false,
  fields: { a: { seen: false, flag: { reason: 'synthetic', note: '' } } },
}))).toBe('flagged')
expect(packetDashboardStatus(packet({
  done: true,
  rejection: { reasons: ['missing_documents'], note: '' },
}))).toBe('flagged')
```

Include explicit cases proving field flags and rejection override both reviewing
and completed.

- [ ] **Step 2: Write failing attention orthogonality tests**

Assert literal ordered reasons for `name`, `unmatched`, `auto-merged`,
`near-threshold`, `length-out-of-range`, duplicate roster flags, and unknown
flags. For each attention fixture, assert its lifecycle is still determined
only by its review.

- [ ] **Step 3: Write failing count/filter/order tests**

Use four lifecycle fixtures plus attention/non-attention fixtures and assert:

```ts
expect(packetDashboardCounts(packets)).toEqual({
  unseen: 1,
  reviewing: 1,
  completed: 1,
  flagged: 1,
})
expect(Object.values(packetDashboardCounts(packets))
  .reduce((sum, count) => sum + count, 0)).toBe(4)
expect(filterPackets(packets, 'reviewing').map(p => p.index)).toEqual([1])
expect(prioritizeAttention(base).map(p => p.index)).toEqual([1, 3, 0, 2])
expect(base.map(p => p.index)).toEqual([0, 1, 2, 3])
```

- [ ] **Step 4: Run pure tests and verify RED**

Run:

```bash
npm test -- src/logic/packetDashboard.test.ts
```

Expected: module import fails because the dashboard derivation does not exist.

- [ ] **Step 5: Implement minimal pure derivation**

Implement the approved precedence and reason mapping in
`src/logic/packetDashboard.ts`. Use a set only for reason deduplication and
ordinary `filter` calls for stable partitioning:

```ts
export function prioritizeAttention<T extends PacketMeta>(packets: T[]): T[] {
  return [
    ...packets.filter(packet => attentionReasons(packet).length > 0),
    ...packets.filter(packet => attentionReasons(packet).length === 0),
  ]
}
```

Return new arrays and never sort or mutate `packets`.

- [ ] **Step 6: Remove the obsolete mixed packet lifecycle**

Update `src/logic/review.ts`, its tests, and `DemoFlow.tsx` so the offline demo
uses `packetDashboardStatus` and the approved labels. Keep `allSeen` and
`calloutAnchor` unchanged. Do not change `packetNeedsResubmit`.

- [ ] **Step 7: Run pure and existing review tests**

Run:

```bash
npm test -- src/logic/packetDashboard.test.ts src/logic/review.test.ts
```

Expected: all tests pass.

- [ ] **Step 8: Commit pure derivation**

```bash
git add src/logic/packetDashboard.ts src/logic/packetDashboard.test.ts src/logic/review.ts src/logic/review.test.ts src/components/DemoFlow.tsx
git commit -m "feat: derive packet dashboard lifecycle"
```

---

### Task 3: Case-Detail Filters, Cards, and Attention Sort

**Files:**
- Create: `src/components/caseDetail.test.tsx`
- Modify: `src/components/CaseDetail.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Consumes: all `packetDashboard.ts` helpers
- Produces: controlled `PacketDashboardView` presentation for component testing
- Preserves: `CaseDetail` public props and packet-open behavior

- [ ] **Step 1: Write failing component presentation tests**

Build a PII-free `CaseDetail` fixture containing all four statuses, one
rejection, field flags, reviewing progress, and multiple attention signals.
Render the real presentation with `renderToStaticMarkup` and assert:

- all five labels and literal counts;
- `.packet-card.unseen`, `.reviewing`, `.completed`, `.flagged`;
- `2/6 đã xem`;
- zero-total fallback `2 trường đã xem`;
- `Đã từ chối · Thiếu chứng từ`;
- `2 trường đã đánh dấu`;
- separate `.packet-attention` containing `!` and `Chỉ khớp theo tên`;
- rejection summary suppresses the field-flag count on the same card.

- [ ] **Step 2: Write failing filter and control tests**

Expose a controlled presentation receiving
`filter`, `attentionFirst`, `onFilter`, and `onAttentionFirst`. Traverse the
real returned React element tree, invoke the actual filter/toggle button
handlers, and assert the callbacks receive:

```ts
'reviewing'
true
```

Render controlled states and assert only matching card names are present.
Render an empty active filter and assert the empty message.

- [ ] **Step 3: Write failing ordering, click, and rerender tests**

Render attention-first on/off controlled states and compare card name order in
the HTML. Invoke a visible card's real `onClick` and assert the synthetic packet
index is passed to `onOpenPacket`. Render the same controlled component with an
updated `detail.packets` fixture and assert counts and membership reflect the
new saved review.

- [ ] **Step 4: Run component tests and verify RED**

Run:

```bash
npm test -- src/components/caseDetail.test.tsx
```

Expected: imports/labels/classes fail because the dashboard presentation is not
implemented.

- [ ] **Step 5: Implement controlled presentation and local state shell**

Refactor `CaseDetail.tsx` without changing its public props:

```ts
export type PacketDashboardFilter = 'all' | PacketDashboardStatus

export function PacketDashboardView(props: {
  packets: PacketMeta[]
  filter: PacketDashboardFilter
  attentionFirst: boolean
  onFilter: (filter: PacketDashboardFilter) => void
  onAttentionFirst: (active: boolean) => void
  onOpenPacket: (index: number) => void
}) { /* derived controls and cards */ }
```

`CaseDetail` owns:

```ts
const [filter, setFilter] = useState<PacketDashboardFilter>('all')
const [attentionFirst, setAttentionFirst] = useState(false)
```

and passes the latest `detail.packets` on every render. Use the canonical
packet-rejection label table already exposed by packet-rejection logic; do not
duplicate a second reason ordering.

- [ ] **Step 6: Implement lifecycle and attention styling**

Replace confidence-based whole-card classes with
`packet-card ${status}`. Add responsive styles for:

```css
.packet-dashboard-controls
.packet-filter
.packet-filter.active
.packet-attention-toggle
.packet-card.unseen
.packet-card.reviewing
.packet-card.completed
.packet-card.flagged
.packet-status-summary
.packet-attention
.packet-grid-empty
```

Use neutral gray, blue, green, and pink/red lifecycle treatments. Limit amber
to `.packet-attention`; retain visible focus and hover states and allow controls
to wrap without horizontal overflow.

- [ ] **Step 7: Run component and presentation regressions**

Run:

```bash
npm test -- src/components/caseDetail.test.tsx src/components/reviewPresentation.test.tsx src/components/packetRejectionDialog.test.tsx
```

Expected: all focused component tests pass.

- [ ] **Step 8: Commit dashboard presentation**

```bash
git add src/components/CaseDetail.tsx src/components/caseDetail.test.tsx src/styles.css
git commit -m "feat: add packet status dashboard"
```

---

### Task 4: Full Regression Verification and Browser QA

**Files:**
- Modify only if a failing regression exposes a dashboard-caused defect; add a
  failing regression test before any fix

**Interfaces:**
- Verifies: frontend, backend, splitter, build, and browser behavior

- [ ] **Step 1: Run the complete automated suites**

Run:

```bash
npm test
python3 -m unittest discover -s server -p '*_test.py' -v
python3 -m unittest discover -s splitter -p '*_test.py' -v
npm run build
```

Expected: zero failures and successful production build.

- [ ] **Step 2: Verify repository boundaries and ports**

Run:

```bash
git status --short --branch
git diff e177cf7 -- vite.config.ts src/upload/api.ts server/app.py
```

Confirm the frontend remains `5174`, `API_BASE` remains `8001`, no generated
PII is staged, and no file under the v2 checkout changed.

- [ ] **Step 3: Start isolated v1 services**

Start the backend using the repository's documented command on
`127.0.0.1:8001`, and start the frontend with:

```bash
npm run dev -- --host 127.0.0.1 --port 5174
```

Keep both sessions available for browser QA.

- [ ] **Step 4: Run browser QA**

At `http://127.0.0.1:5174/`, verify all filter controls/counts, all lifecycle
cards, attention-first stable ordering and restoration, opening/reopening cards,
return-from-review count/membership updates after field review and
flag/rejection saves, normal/narrow desktop widths, and no console/page/network
errors. Do not capture or quote real packet content.

- [ ] **Step 5: Stop services and run final fresh verification**

Stop only the processes started in Step 3. Then rerun:

```bash
npm test
python3 -m unittest discover -s server -p '*_test.py' -v
python3 -m unittest discover -s splitter -p '*_test.py' -v
npm run build
git status --short --branch
```

Expected: all suites/build pass and the worktree contains only intended
committed work plus this plan if not yet committed.

- [ ] **Step 6: Commit the implementation plan if still uncommitted**

```bash
git add docs/superpowers/plans/2026-07-27-packet-status-dashboard.md
git commit -m "docs: plan packet status dashboard"
```

Do not push.
