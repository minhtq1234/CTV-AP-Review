import { useEffect, useRef, useState } from 'react'
import {
  decideCriterionCell,
  fetchPacketCriteria,
  type CriteriaPayload,
  type CriterionCell,
  type CriterionRow,
  type SummaryStatus,
} from '../upload/api'
import {
  cardRows,
  cellFor,
  choicesFor,
  confirms,
  criteriaHeadline,
  groupsInOrder,
  isDecided,
  matrixRows,
  visibleColumns,
} from '../logic/criteriaMatrix'
import { SUMMARY_STATUS_PRESENTATION } from '../logic/summaryTab'
import { cellAction } from '../logic/criteriaDocument'
import type { EvidenceKind } from '../ctv/types'

interface Props {
  caseId: string
  packetIndex: number
  /** Open the document a cell's column refers to. FolderReview owns the dialog. */
  onOpenDocument?: (
    docKind: EvidenceKind,
    context: { label: string; note?: string; value?: string },
  ) => void
  /** Leave for the Tổng hợp tab, where the roster-level criterion is checked. */
  onShowSummary?: () => void
}

const SAVE_ERROR = 'Không lưu được quyết định. Vui lòng thử lại.'

// Acc's 25 criteria for one packet, computed rather than hand-typed. Rows are in
// checklist order inside their sections, because a reviewer works the list; the
// worst-first ordering belongs to the packet list, not to the checklist itself.
export default function CriteriaMatrix({ caseId, packetIndex, onOpenDocument, onShowSummary }: Props) {
  const [payload, setPayload] = useState<CriteriaPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openStt, setOpenStt] = useState<number | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  // Which packet the visible matrix belongs to. A decision enqueued just before
  // a Prev/Next click must not be applied to the next packet's matrix.
  const shownRef = useRef<string>('')

  useEffect(() => {
    let live = true
    const token = `${caseId}:${packetIndex}`
    shownRef.current = token
    setPayload(null)
    setError(null)
    setSaveError(null)
    fetchPacketCriteria(caseId, packetIndex)
      .then(next => { if (live) setPayload(next) })
      .catch(e => { if (live) setError(String(e)) })
    return () => { live = false }
  }, [caseId, packetIndex])

  const decide = async (
    row: CriterionRow, document: string, to: SummaryStatus,
  ) => {
    const token = `${caseId}:${packetIndex}`
    setSaveError(null)
    try {
      await decideCriterionCell(caseId, packetIndex, row.stt, document, to)
      const fresh = await fetchPacketCriteria(caseId, packetIndex)
      // The reviewer may have navigated while this was in flight.
      if (shownRef.current === token) setPayload(fresh)
    } catch {
      if (shownRef.current === token) setSaveError(SAVE_ERROR)
    }
  }

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

      {saveError && (
        <p className="criteria-warning" role="alert">{saveError}</p>
      )}

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
                onDecide={(document, to) => void decide(row, document, to)}
                onOpenDocument={onOpenDocument}
                onShowSummary={onShowSummary}
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

export function MatrixRow({
  row,
  columns,
  open,
  onToggle,
  onDecide,
  onOpenDocument,
  onShowSummary,
}: {
  row: CriterionRow
  columns: string[]
  open: boolean
  onToggle: () => void
  onDecide: (document: string, to: SummaryStatus) => void
  /** Ask the parent to open the document this cell's column refers to. */
  onOpenDocument?: (
    docKind: EvidenceKind,
    context: { label: string; note?: string; value?: string },
  ) => void
  /** The roster-level column is checked on the Tổng hợp tab, not in a packet. */
  onShowSummary?: () => void
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
          return (
            <MatrixCell key={document} row={row} cell={cell}
                        onOpen={onToggle}
                        onOpenDocument={onOpenDocument}
                        onShowSummary={onShowSummary} />
          )
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
                  <CellDecision row={row} cell={cell} onDecide={onDecide} />
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  )
}

function MatrixCell({ row, cell, onOpen, onOpenDocument, onShowSummary }: {
  row: CriterionRow
  cell: CriterionCell
  onOpen: () => void
  onOpenDocument?: (
    docKind: EvidenceKind,
    context: { label: string; note?: string; value?: string },
  ) => void
  onShowSummary?: () => void
}) {
  const status = SUMMARY_STATUS_PRESENTATION[cell.status]
  const located = cell.evidence.some(e => e.bbox)
  const decided = isDecided(cell)
  const action = cellAction(cell.document, cell.status)

  return (
    <td className={`criteria-cell ${status.tone}`}>
      {/* Opens the column's document full-page, carrying this cell's note and
          value into the popup's header. The detail row stays: the caret still
          opens it, and it is the only place that lists every column's note at
          once. `Excel` is a reference value with no document, so it stays inert;
          `Bảng Kê Thu Mua` is roster-level and goes to Tổng hợp. */}
      <button
        type="button"
        className={`criteria-mark${decided ? ' decided' : ''}`}
        title={cell.note}
        aria-haspopup={action.kind === 'open' ? 'dialog' : undefined}
        disabled={action.kind === 'none'}
        aria-label={`${row.label} · ${cell.document}: ${status.label}`}
        onClick={() => {
          if (action.kind === 'open') {
            if (onOpenDocument) {
              onOpenDocument(action.docKind, {
                label: `${row.label} · ${cell.document}`,
                note: cell.note,
                value: cell.value,
              })
            } else {
              // No handler wired: fall back to the detail row rather than
              // becoming a button that does nothing.
              onOpen()
            }
          } else if (action.kind === 'summary') {
            onShowSummary?.()
          }
        }}
      >
        <span aria-hidden="true">{status.icon}</span>
      </button>
      {cell.value && (
        <span className={`criteria-value${located ? ' located' : ''}`}>
          {cell.value}
        </span>
      )}
    </td>
  )
}

function CellDecision({ row, cell, onDecide }: {
  row: CriterionRow
  cell: CriterionCell
  onDecide: (document: string, to: SummaryStatus) => void
  /** Ask the parent to open the document this cell's column refers to. */
  onOpenDocument?: (
    docKind: EvidenceKind,
    context: { label: string; note?: string; value?: string },
  ) => void
  /** The roster-level column is checked on the Tổng hợp tab, not in a packet. */
  onShowSummary?: () => void
}) {
  const choices = choicesFor(cell)
  if (!choices.length) return null

  return (
    <span className="criteria-decide" role="group"
          aria-label={`Quyết định cho ${row.label} · ${cell.document}`}>
      {isDecided(cell) && cell.computedStatus && (
        <span className="criteria-computed">
          Công cụ: {SUMMARY_STATUS_PRESENTATION[cell.computedStatus].label}
        </span>
      )}
      {choices.map(to => (
        <button
          key={to}
          type="button"
          className={`criteria-decide-btn ${SUMMARY_STATUS_PRESENTATION[to].tone}`
            + (confirms(cell, to) ? ' confirming' : '')}
          onClick={() => onDecide(cell.document, to)}
        >
          {confirms(cell, to)
            ? `Xác nhận: ${SUMMARY_STATUS_PRESENTATION[to].label}`
            : SUMMARY_STATUS_PRESENTATION[to].label}
        </button>
      ))}
    </span>
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
