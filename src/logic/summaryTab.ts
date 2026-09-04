// Presentation logic for the Tổng hợp tab — the five criteria Acc's checklist
// marks `Toàn bảng kê` rather than per-CTV. The statuses come from the backend
// (server/summary_criteria.py); everything here is how they get read.
import type { SummaryCriterion, SummaryPayload, SummaryStatus } from '../upload/api'

export type StatusTone = 'good' | 'bad' | 'attention' | 'unknown' | 'muted'

/** Worst first, so what needs work is at the top. Mirrors `criteria.roll_up`. */
const SEVERITY: Record<SummaryStatus, number> = {
  no: 0,
  missing: 1,
  rv: 2,
  pending: 3,
  ok: 4,
  na: 5,
}

export const SUMMARY_STATUS_PRESENTATION: Record<
  SummaryStatus,
  { icon: string; label: string; tone: StatusTone }
> = {
  ok: { icon: '✓', label: 'Đạt', tone: 'good' },
  no: { icon: '×', label: 'Không khớp', tone: 'bad' },
  rv: { icon: '!', label: 'Cần người kiểm tra', tone: 'attention' },
  missing: { icon: '⊘', label: 'Thiếu chứng từ', tone: 'bad' },
  // Not the same as `ok`: nothing was evaluated. Keeping these apart is the
  // reason this tab exists rather than defaulting every unchecked cell to pass.
  pending: { icon: '?', label: 'Chưa kiểm tra được', tone: 'unknown' },
  na: { icon: '–', label: 'Không áp dụng', tone: 'muted' },
}

/** A pending cell's real meaning, when the engine recorded one.
 *
 *  `? Chưa kiểm tra được` was doing five jobs at once. Measured over 166 real
 *  packets and 4,813 pending cells: 41% `not-automated` (no extractor exists
 *  for that criterion at all -- the same answer on every packet for ever),
 *  14% `roster-level` (the batch-level bảng kê, which IS checked, on the Tổng
 *  hợp tab), 12% `no-roster-value` (the submitter left the cell empty), 15%
 *  `unread` (the document is here and its value would not read) and the rest
 *  unmatched or `blocked` (a computed criterion whose inputs did not read --
 *  332 cells, the second-largest bucket, and the one this map used to name in
 *  prose while having no entry for it). The corpus was measured before #15's
 *  PIT > 0 cells moved from `blocked` to `not-automated`, so that split shifts
 *  by one criterion's worth; the ordering it argues from does not.
 *
 *  Only `unread`, `unmatched` and `blocked` are facts about the packet in
 *  front of the reviewer. Showing all of them identically taught reviewers to
 *  skip the chip, and with it the ones that matter. `not-automated` and
 *  `roster-level` are muted on purpose -- they read as scope, like `Không áp
 *  dụng`, rather than as uncertainty about this submission.
 *
 *  Keyed by string, not by `PendingReason`: a newer server's reason must fall
 *  back through `cellPresentation` rather than throw. `summaryTab.test.ts`
 *  pins these keys to `PENDING_REASONS` and to the engine's own literals, so
 *  the looseness cannot hide a missing entry.
 */
export const PENDING_REASON_PRESENTATION: Record<
  string,
  { icon: string; label: string; tone: StatusTone }
> = {
  'not-automated': {
    icon: '⋯', label: 'Chưa có kiểm tra tự động', tone: 'muted',
  },
  'roster-level': {
    icon: '⊙', label: 'Kiểm tra ở tab Tổng hợp', tone: 'muted',
  },
  'no-roster-value': {
    icon: '⊘', label: 'Bảng kê chưa ghi giá trị', tone: 'attention',
  },
  unread: {
    icon: '?', label: 'Chưa đọc được giá trị trên chứng từ', tone: 'unknown',
  },
  unmatched: {
    icon: '?', label: 'Gói chưa khớp dòng bảng kê', tone: 'unknown',
  },
  // Not muted, unlike the two scope reasons above. `blocked` now has exactly
  // one stamp site, `evaluate._pending_compute`, and it means a computation
  // that exists and will answer as soon as its inputs read -- #12 waiting on
  // #10/#11, 332 cells, a fact about THIS packet. (It used to have two, and
  // the other one -- #15 at PIT > 0, where no rate is coded and no input will
  // ever unblock it -- moved to `not-automated`, which is why that reading is
  // no longer ambiguous.) Muting a chip that is about the packet in front of
  // the reviewer is the more expensive of the two mistakes, so it sits with
  // `unread`/`unmatched`. The cell's own `note` carries the specific sentence.
  blocked: {
    icon: '?', label: 'Chưa tính được: thiếu giá trị đầu vào', tone: 'unknown',
  },
  // A person deliberately moved a settled cell back to pending, so the engine
  // has no reason of its own to give. Outstanding work someone asked for, not
  // an unknown: `attention`, like an empty bảng kê cell.
  override: {
    icon: '!', label: 'Người kiểm tra đưa về chưa kiểm tra', tone: 'attention',
  },
}

/** How one cell should read: its status, refined by why it is pending. */
export function cellPresentation(
  cell: { status: SummaryStatus; pendingReason?: string | null },
): { icon: string; label: string; tone: StatusTone } {
  if (cell.status === 'pending' && cell.pendingReason) {
    return PENDING_REASON_PRESENTATION[cell.pendingReason]
      ?? SUMMARY_STATUS_PRESENTATION.pending
  }
  return SUMMARY_STATUS_PRESENTATION[cell.status]
}

/** What the backend could not reach, in the reviewer's terms. */
export const MISSING_LABELS: Record<string, string> = {
  rosterRows: 'Chưa đọc được dòng CTV nào trên bảng kê',
  purchaseTotal: 'Chưa có số tổng từ Bảng Kê Thu Mua để đối chiếu',
  packets: 'Chưa có gói hồ sơ nào đã khớp bảng kê',
}

export function worstFirst(criteria: SummaryCriterion[]): SummaryCriterion[] {
  return [...criteria].sort(
    (a, b) => SEVERITY[a.status] - SEVERITY[b.status] || a.stt - b.stt,
  )
}

const HEADLINE_ORDER: Array<[SummaryStatus, string]> = [
  ['no', 'không khớp'],
  ['missing', 'thiếu chứng từ'],
  ['rv', 'cần người kiểm tra'],
  ['pending', 'chưa kiểm tra được'],
  ['ok', 'đạt'],
  ['na', 'không áp dụng'],
]

/** The tab header, problems first. Only non-zero statuses are named. */
export function headlineParts(payload: SummaryPayload): string[] {
  const rows = payload.people
    ? `${payload.people} dòng bảng kê`
    : 'chưa đọc được dòng nào'
  const counted = HEADLINE_ORDER
    .filter(([status]) => payload.counts[status] > 0)
    .map(([status, word]) => `${payload.counts[status]} ${word}`)
  return [rows, ...counted]
}

/** One line per input the tab could not reach, so a pending cell explains itself. */
export function gapNotes(payload: SummaryPayload): string[] {
  return payload.missing.map(key => MISSING_LABELS[key] ?? key)
}
