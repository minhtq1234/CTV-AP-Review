import type { CaseSummary, CaseState, Progress } from '../upload/api'
import { caseProgressLabel, progressPct, stageLabel } from '../upload/api'

interface Props {
  cases: CaseSummary[]
  live?: Record<string, Progress>   // live OCR progress per processing case
  onOpen: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}

// Vietnamese labels for the case-level status pill (distinct from a packet's
// decision badge — this is the whole submission's lifecycle).
const STATUS_LABEL: Record<CaseState, string> = {
  processing: 'Đang xử lý…',
  ready: 'Sẵn sàng',
  in_review: 'Đang xem',
  done: 'Hoàn tất',
  error: 'Lỗi',
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('vi-VN')
}

// The landing screen of the "Tải hồ sơ" mode: every past + in-flight upload as
// a row (name, date, status, review progress), open to resume, delete to remove.
export default function CaseList({ cases, live, onOpen, onNew, onDelete }: Props) {
  return (
    <div className="case-list">
      <div className="case-list-head">
        <h2>Hồ sơ đã tải lên</h2>
        <button className="btn primary" onClick={onNew}>+ Tải hồ sơ mới</button>
      </div>

      {cases.length === 0 ? (
        <p className="case-list-empty">Chưa có hồ sơ nào — bấm "+ Tải hồ sơ mới" để bắt đầu.</p>
      ) : (
        <div className="case-rows">
          {cases.map(c => {
            const processing = c.status === 'processing'
            const lp = live?.[c.id]
            // Follows PacketTable's row pattern: a div carrying role/tabIndex
            // rather than a real <button>, because the row contains its own
            // delete button and nesting one button inside another is invalid.
            return (
              <div
                key={c.id}
                className={`case-row${processing ? ' processing' : ''}`}
                role="button"
                tabIndex={processing ? -1 : 0}
                aria-disabled={processing || undefined}
                aria-label={`${c.name} · ${STATUS_LABEL[c.status]}`}
                onClick={() => { if (!processing) onOpen(c.id) }}
                onKeyDown={event => {
                  // Enter on the delete button must delete and nothing else;
                  // without this the keypress bubbles and also opens the case.
                  if (event.target !== event.currentTarget) return
                  if (processing) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onOpen(c.id)
                  }
                }}
              >
                <div className="case-row-main">
                  <span className="case-row-name">{c.name}</span>
                  <span className="case-row-date">{fmtDate(c.createdAt)}</span>
                </div>
                <span className={`case-pill ${c.status}`}>{STATUS_LABEL[c.status]}</span>
                {processing ? (
                  <div className="case-row-live">
                    <div className="mini-bar">
                      <div className="mini-bar-fill" style={{ width: `${lp ? progressPct(lp) : 0}%` }} />
                    </div>
                    <span className="case-row-live-text">
                      {lp && lp.total
                        ? `gói ${lp.done}/${lp.total}${lp.detail ? ' · ' + lp.detail : ''}`
                        : stageLabel(lp?.stage ?? 'queued')}
                    </span>
                  </div>
                ) : (
                  <span className="case-row-progress">{caseProgressLabel(c.progress)}</span>
                )}
                <button
                  className="btn case-row-delete"
                  onClick={e => { e.stopPropagation(); onDelete(c.id) }}
                  title="Xoá hồ sơ"
                >
                  Xoá
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
