import type { CaseSummary, CaseState } from '../upload/api'
import { caseProgressLabel } from '../upload/api'

interface Props {
  cases: CaseSummary[]
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
export default function CaseList({ cases, onOpen, onNew, onDelete }: Props) {
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
          {cases.map(c => (
            <div key={c.id} className="case-row" onClick={() => onOpen(c.id)}>
              <div className="case-row-main">
                <span className="case-row-name">{c.name}</span>
                <span className="case-row-date">{fmtDate(c.createdAt)}</span>
              </div>
              <span className={`case-pill ${c.status}`}>{STATUS_LABEL[c.status]}</span>
              <span className="case-row-progress">{caseProgressLabel(c.progress)}</span>
              <button
                className="btn case-row-delete"
                onClick={e => { e.stopPropagation(); onDelete(c.id) }}
                title="Xoá hồ sơ"
              >
                Xoá
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
