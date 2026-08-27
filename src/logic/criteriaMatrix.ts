// Presentation logic for Acc's 25-criterion matrix. The statuses come from the
// engine (server/evaluate.py); everything here is how they get laid out.
import type {
  CriteriaPayload,
  CriterionCell,
  CriterionRow,
  SummaryStatus,
} from '../upload/api'

/** Only the columns some matrix criterion actually spans, in payload order. */
export function visibleColumns(
  documents: string[],
  rows: CriterionRow[],
): string[] {
  const spanned = new Set(
    matrixRows(rows).flatMap(r => r.cells.map(c => c.document)),
  )
  return documents.filter(d => spanned.has(d))
}

/**
 * A criterion's cell for one column, or null when the criterion does not span
 * that document — which renders as a static dash rather than a clickable `na`.
 */
export function cellFor(row: CriterionRow, document: string): CriterionCell | null {
  return row.cells.find(c => c.document === document) ?? null
}

export function matrixRows(rows: CriterionRow[]): CriterionRow[] {
  return rows.filter(r => r.render === 'matrix')
}

/**
 * The criteria the prototype lifted out of the matrix into their own cards —
 * computed values and single-source checks, where one row of ticks says less
 * than a sentence.
 */
export function cardRows(rows: CriterionRow[]): CriterionRow[] {
  return rows.filter(r => r.render === 'card')
}

export interface MatrixGroup {
  code: string
  label: string
  counts: Record<SummaryStatus, number>
}

export function groupsInOrder(
  groups: CriteriaPayload['groups'],
): MatrixGroup[] {
  return Object.entries(groups)
    .map(([code, group]) => ({ code, ...group }))
    .sort((a, b) => a.code.localeCompare(b.code))
}

const HEADLINE_ORDER: Array<[SummaryStatus, string]> = [
  ['no', 'không khớp'],
  ['missing', 'thiếu chứng từ'],
  ['rv', 'cần người kiểm tra'],
  ['pending', 'chưa kiểm tra được'],
  ['ok', 'đạt'],
  ['na', 'không áp dụng'],
]

/**
 * The header line, problems first. Counts criteria rather than cells: a
 * criterion spanning five documents must not weigh five times as much as one
 * spanning a single document.
 */
export function criteriaHeadline(payload: CriteriaPayload): string[] {
  const total = payload.matchedRoster
    ? `${payload.criteria.length} tiêu chí`
    : 'chưa khớp bảng kê'
  return [
    total,
    ...HEADLINE_ORDER
      .filter(([status]) => (payload.counts[status] ?? 0) > 0)
      .map(([status, word]) => `${payload.counts[status]} ${word}`),
  ]
}

/**
 * The statuses a person can decide. `na` is absent on purpose: it says the
 * document is outside the criterion — a fact about the checklist, not a
 * judgment, so there is nothing to decide.
 */
export const DECIDABLE_STATUSES: SummaryStatus[] = [
  'ok', 'no', 'rv', 'missing', 'pending',
]

/** Whether a reviewer's decision is standing on this cell. */
export function isDecided(cell: CriterionCell): boolean {
  return !!cell.computedStatus && cell.computedStatus !== cell.status
}

/** Address a cell the way the server keys it: `21:Hợp đồng`. */
export function decisionKey(stt: number, document: string): string {
  return `${String(stt).padStart(2, '0')}:${document}`
}

/**
 * What this cell can be decided to — including its current status, which records
 * a *confirmation*.
 *
 * Confirming is not a no-op. Without it a reviewer who agrees with a computed
 * `no` has no way to say so, and `cần gửi lại` — which counts conclusions, not
 * candidates — would sit at zero forever.
 *
 * Nothing at all for a cell outside the criterion or marked `na`: that states a
 * fact about the checklist, not a judgment.
 */
export function choicesFor(cell: CriterionCell | null): SummaryStatus[] {
  if (!cell || cell.status === 'na') return []
  return DECIDABLE_STATUSES
}

/** Whether choosing `to` on this cell records agreement rather than a change. */
export function confirms(cell: CriterionCell, to: SummaryStatus): boolean {
  return cell.status === to
}
