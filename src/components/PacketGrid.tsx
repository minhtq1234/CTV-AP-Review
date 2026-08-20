import type { CtvFolder } from '../ctv/types'
import {
  buildPacketGrid,
  type PacketGridStatus,
} from '../logic/packetGrid'
import { formatRosterValue } from '../logic/reviewValue'

interface Props {
  folder: CtvFolder
  onOpenEvidence: (fieldKey: string, sourceIndex: number) => void
}

const STATUS_PRESENTATION: Record<PacketGridStatus, { icon: string; label: string }> = {
  match: { icon: '✓', label: 'Khớp' },
  review: { icon: '!', label: 'Cần review' },
  mismatch: { icon: '×', label: 'Không khớp' },
  na: { icon: '–', label: 'Không áp dụng' },
}

export default function PacketGrid({ folder, onOpenEvidence }: Props) {
  const grid = buildPacketGrid(folder)

  return (
    <section className="packet-grid-view" aria-label="Dạng bảng đối chiếu chứng từ">
      <div className="packet-grid-scroll">
        <table className="packet-grid-table">
          <thead>
            <tr>
              <th className="packet-grid-order">STT</th>
              <th className="packet-grid-field">Trường</th>
              <th className="packet-grid-excel">Excel file</th>
              {grid.columns.map((column, index) => (
                <th key={column.docId} className="packet-grid-document">
                  <span className="packet-grid-doc-order">{index + 1}</span>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row, rowIndex) => {
              const field = folder.fields.find(candidate => candidate.key === row.fieldKey)!
              return (
                <tr key={row.fieldKey}>
                  <td className="packet-grid-order">{rowIndex + 1}</td>
                  <th scope="row" className="packet-grid-field">{row.label}</th>
                  <td className="packet-grid-excel-value">{formatRosterValue(field) || '—'}</td>
                  {row.cells.map((cell, columnIndex) => {
                    const presentation = STATUS_PRESENTATION[cell.status]
                    const label = `${row.label} · Chứng từ ${columnIndex + 1} ${grid.columns[columnIndex].label}: ${presentation.label}`
                    return (
                      <td key={grid.columns[columnIndex].docId} className="packet-grid-cell">
                        {cell.sourceIndex == null ? (
                          <span className={`packet-grid-status ${cell.status}`} aria-label={label}>
                            {presentation.icon}
                          </span>
                        ) : (
                          <button
                            type="button"
                            className={`packet-grid-status ${cell.status}`}
                            aria-label={label}
                            title={`${presentation.label} — mở chứng từ`}
                            onClick={() => onOpenEvidence(row.fieldKey, cell.sourceIndex!)}
                          >
                            {presentation.icon}
                          </button>
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={2} className="packet-grid-result-label">Kết quả</th>
              <td />
              {grid.summaries.map(summary => (
                <td key={summary.docId} className={`packet-grid-result ${summary.status}`}>
                  {summary.status === 'na' ? '—' : STATUS_PRESENTATION[summary.status].label}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="packet-grid-legend" aria-label="Chú giải">
        {(['match', 'review', 'mismatch', 'na'] as const).map(status => (
          <span key={status}>
            <i className={status} />
            {STATUS_PRESENTATION[status].label}
          </span>
        ))}
      </div>
    </section>
  )
}
