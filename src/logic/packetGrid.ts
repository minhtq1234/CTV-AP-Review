import type { CtvFolder } from '../ctv/types'
import { evalField, type SourceVerdict } from '../ctv/checks'

export type PacketGridStatus = 'match' | 'review' | 'mismatch' | 'na'

export interface PacketGridCell {
  status: PacketGridStatus
  sourceIndex?: number
}

export interface PacketGridModel {
  columns: Array<{ docId: string; label: string }>
  rows: Array<{
    fieldKey: string
    label: string
    expected: string
    cells: PacketGridCell[]
  }>
  summaries: Array<{ docId: string; status: PacketGridStatus }>
}

const STATUS_SEVERITY: Record<PacketGridStatus, number> = {
  mismatch: 0,
  review: 1,
  match: 2,
  na: 3,
}

function gridStatus(verdict: SourceVerdict): PacketGridStatus {
  if (verdict === 'mismatch') return 'mismatch'
  if (verdict === 'match') return 'match'
  return 'review'
}

function mostSevere(cells: PacketGridCell[]): PacketGridCell {
  return cells.reduce((worst, cell) => (
    STATUS_SEVERITY[cell.status] < STATUS_SEVERITY[worst.status] ? cell : worst
  ), { status: 'na' })
}

export function buildPacketGrid(folder: CtvFolder): PacketGridModel {
  const columns = folder.docs.map(doc => ({ docId: doc.id, label: doc.label }))
  const rows = folder.fields.map(field => {
    const result = evalField(field, folder)
    const cells = columns.map(column => {
      const candidates = result.sources.flatMap(sourceResult => {
        if (sourceResult.source.docId !== column.docId) return []
        return [{
          status: gridStatus(sourceResult.verdict),
          sourceIndex: field.sources.findIndex(source => source === sourceResult.source),
        } satisfies PacketGridCell]
      })
      return candidates.length ? mostSevere(candidates) : { status: 'na' as const }
    })
    return {
      fieldKey: field.key,
      label: field.label,
      expected: field.expected,
      cells,
    }
  })
  const summaries = columns.map((column, columnIndex) => ({
    docId: column.docId,
    status: mostSevere(rows.map(row => row.cells[columnIndex])).status,
  }))

  return { columns, rows, summaries }
}
