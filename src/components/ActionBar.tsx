import { useState } from 'react'
import type { CaseStatus } from '../types'

interface ActionBarProps { status: CaseStatus; rejectReason?: string; hint?: string; onApprove: () => void; onReject: (reason: string) => void }

export default function ActionBar({ status, rejectReason, hint, onApprove, onReject }: ActionBarProps) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  if (status !== 'pending') {
    return (
      <div className="action-bar">
        <span className={`final ${status}`}>
          {status === 'approved' ? '✓ Đã phê duyệt' : '✗ Đã từ chối'}
          {status === 'rejected' && rejectReason ? <span className="final-reason"> — {rejectReason}</span> : null}
        </span>
      </div>
    )
  }

  return (
    <div className="action-bar">
      <span className="hint">{hint ?? '↑ ↓ chuyển trường · ⌘K nhảy nhanh'}</span>
      <div className="actions">
        {rejecting && (
          <input className="reason" autoFocus placeholder="Lý do (tuỳ chọn)"
            value={reason} onChange={e => setReason(e.target.value)} />
        )}
        <button className="btn" onClick={() => (rejecting ? onReject(reason) : setRejecting(true))}>✗ Từ chối</button>
        <button className="btn primary" onClick={onApprove}>✓ Phê duyệt</button>
      </div>
    </div>
  )
}
