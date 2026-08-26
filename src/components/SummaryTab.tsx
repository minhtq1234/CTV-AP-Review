import { useEffect, useState } from 'react'
import { fetchCaseSummary, type SummaryCriterion, type SummaryPayload } from '../upload/api'
import {
  gapNotes,
  headlineParts,
  SUMMARY_STATUS_PRESENTATION,
  worstFirst,
} from '../logic/summaryTab'

interface Props {
  caseId: string
}

// The Tổng hợp tab: the five criteria Acc's checklist marks `Toàn bảng kê`
// rather than per-CTV, so they have no packet to live on. Worst first, each
// carrying Acc's own instruction — the reviewer still has to act when the tool
// abstains, and most of these criteria abstain today.
export default function SummaryTab({ caseId }: Props) {
  const [payload, setPayload] = useState<SummaryPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setPayload(null)
    setError(null)
    fetchCaseSummary(caseId)
      .then(next => { if (live) setPayload(next) })
      .catch(e => { if (live) setError(String(e)) })
    return () => { live = false }
  }, [caseId])

  if (error) {
    return (
      <div className="summary-tab-empty" role="alert">
        Không tải được tab Tổng hợp: {error}
      </div>
    )
  }
  if (!payload) {
    return <div className="summary-tab-empty">Đang kiểm tra toàn bảng kê…</div>
  }

  const gaps = gapNotes(payload)

  return (
    <section className="summary-tab" aria-label="Tổng hợp toàn bảng kê">
      <div className="summary-tab-head">
        <h3>Kiểm tra toàn bảng kê</h3>
        <p className="summary-tab-headline">{headlineParts(payload).join(' · ')}</p>
        {payload.rosterName && (
          <p className="summary-tab-source">Nguồn: {payload.rosterName}</p>
        )}
      </div>

      {gaps.length > 0 && (
        <ul className="summary-tab-gaps" aria-label="Dữ liệu còn thiếu">
          {gaps.map(note => <li key={note}>{note}</li>)}
        </ul>
      )}

      <ol className="summary-criteria">
        {worstFirst(payload.criteria).map(criterion => (
          <SummaryCriterionCard key={criterion.stt} criterion={criterion} />
        ))}
      </ol>
    </section>
  )
}

export function SummaryCriterionCard({ criterion }: { criterion: SummaryCriterion }) {
  const [open, setOpen] = useState(false)
  const status = SUMMARY_STATUS_PRESENTATION[criterion.status]

  return (
    <li className={`summary-criterion ${status.tone}`}>
      <div className="summary-criterion-head">
        <span className="summary-criterion-stt">#{criterion.stt}</span>
        <span className="summary-criterion-label">{criterion.label}</span>
        <span
          className={`summary-criterion-status ${status.tone}`}
          aria-label={`${criterion.label}: ${status.label}`}
        >
          <span aria-hidden="true">{status.icon}</span> {status.label}
        </span>
      </div>

      <p className="summary-criterion-message">{criterion.message}</p>

      {criterion.detail.length > 0 && (
        <ul className="summary-criterion-detail">
          {criterion.detail.map(item => <li key={item}>{item}</li>)}
        </ul>
      )}

      <div className="summary-criterion-foot">
        <span className="summary-criterion-docs">
          {criterion.docs.join(' · ')}
        </span>
        <button
          type="button"
          className="summary-criterion-how-toggle"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? 'Ẩn cách kiểm tra' : 'Cách kiểm tra'}
        </button>
      </div>

      {open && <p className="summary-criterion-how">{criterion.how}</p>}
    </li>
  )
}
