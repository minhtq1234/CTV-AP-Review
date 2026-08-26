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
