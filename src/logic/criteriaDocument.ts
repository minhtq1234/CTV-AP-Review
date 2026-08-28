// The matrix's columns are criteria column names (server/criteria.py:35-42).
// A packet's documents have kinds (manifest.json -> docs[].kind). They are not
// the same vocabulary and nothing mapped between them before this.
import type { EvidenceKind } from '../ctv/types'

/** Criteria column name -> the document kind that column refers to. */
const KIND_BY_COLUMN: Record<string, EvidenceKind> = {
  'Hợp đồng': 'contract',
  'BBNT': 'bbnt',
  'Phụ lục/KPI': 'appendix',
  'Cam kết PIT': 'commitment',
  // Named for MST, but the document is the tax-lookup page and its kind is
  // `pit`. The two names disagree; the kind is what the manifest holds.
  'Website tra cứu MST': 'pit',
  // The front. The back is one tab away inside the viewer, so the click does
  // not have to decide between them.
  'CCCD/Passport': 'id_front',
}

/** `Excel` is the reference value and `Bảng Kê Thu Mua` spans the whole bảng
 *  kê, so neither has a document in this packet. */
export function documentKindForColumn(column: string): EvidenceKind | null {
  return KIND_BY_COLUMN[column] ?? null
}

export type CellAction =
  | { kind: 'open'; docKind: EvidenceKind }
  | { kind: 'summary' }
  | { kind: 'none' }

/** What clicking this cell should do. `na` never opens anything: the criterion
 *  does not apply to that document, so there is nothing to look at and the
 *  cell's note already explains why. */
export function cellAction(column: string, status: string): CellAction {
  if (status === 'na') return { kind: 'none' }
  if (column === 'Bảng Kê Thu Mua') return { kind: 'summary' }
  const docKind = documentKindForColumn(column)
  return docKind ? { kind: 'open', docKind } : { kind: 'none' }
}
