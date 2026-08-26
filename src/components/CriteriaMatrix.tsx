import { useEffect, useState } from 'react'
import {
  fetchPacketCriteria,
  type CriteriaPayload,
  type CriterionCell,
  type CriterionRow,
} from '../upload/api'
import {
  cardRows,
  cellFor,
  criteriaHeadline,
  groupsInOrder,
  matrixRows,
  visibleColumns,
} from '../logic/criteriaMatrix'
import { SUMMARY_STATUS_PRESENTATION } from '../logic/summaryTab'

interface Props {
  caseId: string
  packetIndex: number
}

// Acc's 25 criteria for one packet, computed rather than hand-typed. Rows are in
// checklist order inside their sections, because a reviewer works the list; the
// worst-first ordering belongs to the packet list, not to the checklist itself.
export default function CriteriaMatrix({ caseId, packetIndex }: Props) {
  const [payload, setPayload] = useState<CriteriaPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openStt, setOpenStt] = useState<number | null>(null)

  useEffect(() => {
    let live = true
    setPayload(null)
    setError(null)
    fetchPacketCriteria(caseId, packetIndex)
      .then(next => { if (live) setPayload(next) })
      .catch(e => { if (live) setError(String(e)) })
    return () => { live = false }
  }, [caseId, packetIndex])

  if (error) {
    return (
      <div className="criteria-empty" role="alert">
        Không tải được bảng tiêu chí: {error}
      </div>
    )
  }
  if (!payload) {
    return <div className="criteria-empty">Đang đối chiếu 25 tiêu chí…</div>
  }

  const rows = matrixRows(payload.criteria)
  const columns = visibleColumns(payload.documents, payload.criteria)

  return (
    <section className="criteria-view" aria-label="Bảng 25 tiêu chí kiểm tra">
      <div className="criteria-head">
        <p className="criteria-headline">
          {criteriaHeadline(payload).join(' · ')}
        </p>
        <div className="criteria-group-counts">
          {groupsInOrder(payload.groups).map(group => (
            <span key={group.code} className="criteria-group-pill">
              {group.label}
              <b>{group.counts.ok}/{Object.values(group.counts)
                .reduce((n, v) => n + v, 0)}</b>
            </span>
          ))}
        </div>
      </div>

      {!payload.matchedRoster && (
        <p className="criteria-warning">
          Gói hồ sơ chưa khớp dòng nào trên bảng kê, nên không có giá trị tham
          chiếu để đối chiếu.
        </p>
      )}

      <div className="criteria-scroll">
        <table className="criteria-table">
          <thead>
            <tr>
              <th className="criteria-stt">STT</th>
              <th className="criteria-label">Tiêu chí</th>
              {columns.map(document => (
                <th key={document} className="criteria-doc">{document}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <MatrixRow
                key={row.stt}
                row={row}
                columns={columns}
                open={openStt === row.stt}
                onToggle={() => setOpenStt(openStt === row.stt ? null : row.stt)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="criteria-cards">
        {cardRows(payload.criteria).map(row => (
          <CriterionCard key={row.stt} row={row} />
        ))}
      </div>
    </section>
  )
}

function MatrixRow({
  row,
  columns,
  open,
  onToggle,
}: {
  row: CriterionRow
  columns: string[]
  open: boolean
  onToggle: () => void
}) {
  const status = SUMMARY_STATUS_PRESENTATION[row.status]

  return (
    <>
      <tr className={`criteria-row ${status.tone}`}>
        <td className="criteria-stt">
          <button
            type="button"
            className="criteria-stt-toggle"
            aria-expanded={open}
            onClick={onToggle}
          >
            {row.code}
          </button>
        </td>
        <td className="criteria-label">{row.label}</td>
        {columns.map(document => {
          const cell = cellFor(row, document)
          if (!cell) {
            // Not part of this criterion: a static dash, not a clickable state.
            return (
              <td key={document} className="criteria-cell out-of-scope">
                <span aria-hidden="true">–</span>
                <span className="sr-only">Không thuộc tiêu chí này</span>
              </td>
            )
          }
          return <MatrixCell key={document} row={row} cell={cell} />
        })}
      </tr>
      {open && (
        <tr className="criteria-detail-row">
          <td colSpan={columns.length + 2}>
            <p className="criteria-how">{row.how}</p>
            <ul className="criteria-cell-notes">
              {row.cells.map(cell => (
                <li key={cell.document}>
                  <b>{cell.document}</b>
                  {cell.value && <span className="criteria-read">{cell.value}</span>}
                  <span>{cell.note}</span>
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  )
}

function MatrixCell({ row, cell }: { row: CriterionRow; cell: CriterionCell }) {
  const status = SUMMARY_STATUS_PRESENTATION[cell.status]
  const located = cell.evidence.some(e => e.bbox)

  return (
    <td className={`criteria-cell ${status.tone}`}>
      <span
        className="criteria-mark"
        title={cell.note}
        aria-label={`${row.label} · ${cell.document}: ${status.label}`}
      >
        <span aria-hidden="true">{status.icon}</span>
      </span>
      {cell.value && (
        <span className={`criteria-value${located ? ' located' : ''}`}>
          {cell.value}
        </span>
      )}
    </td>
  )
}

function CriterionCard({ row }: { row: CriterionRow }) {
  const status = SUMMARY_STATUS_PRESENTATION[row.status]
  const note = row.note || row.cells[0]?.note || ''

  return (
    <div className={`criterion-card ${status.tone}`}>
      <div className="criterion-card-head">
        <span className="criterion-card-stt">#{row.stt}</span>
        <span className="criterion-card-label">{row.label}</span>
        <span className={`criterion-card-status ${status.tone}`}>
          <span aria-hidden="true">{status.icon}</span> {status.label}
        </span>
      </div>
      <p className="criterion-card-note">{note}</p>
    </div>
  )
}
