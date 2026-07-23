import type { CheckItem } from '../ctv/types'
import type { PacketReview, FieldFlag } from '../upload/api'

interface Props {
  checks: CheckItem[]
  review: PacketReview
  selectedCode: string
  onSelect: (code: string) => void
  onToggleFlag: (code: string, flag: FieldFlag | null) => void
}

// Three reviewer-progress states only. The tool does NOT surface its own auto-compare
// guess in the status column: the reviewer validates with their own eyes, and the column
// tracks what THEY did — not looked at yet (blank) / looked at / flagged for resubmission.
type RowStatus = 'unseen' | 'seen' | 'flag'

function rowStatus(ir?: { seen: boolean; flag: FieldFlag | null }): RowStatus {
  if (ir?.flag) return 'flag'
  return ir?.seen ? 'seen' : 'unseen'
}

// State lives entirely in the dot glyph — hollow ring (chưa xem) / ✓ (đã xem) / ⚑ (đã
// đánh dấu). No redundant text label beside it.
const DOT_GLYPH: Record<RowStatus, string> = { unseen: '', seen: '✓', flag: '⚑' }

const FLAG_REASONS = ['sai', 'thiếu', 'mờ, không đọc được']

export default function ChecklistPanel({ checks, review, selectedCode, onSelect, onToggleFlag }: Props) {
  const gates = checks.filter(c => c.tier === 'gate')
  const detail = checks.filter(c => c.tier === 'detail')
  const total = checks.length
  const seen = checks.filter(c => review.items[c.code]?.seen).length
  const pct = total ? Math.round((seen / total) * 100) : 0
  // "Đủ điều kiện" = every precondition has been looked at and none flagged.
  const allGatesOk = gates.length > 0 && gates.every(g => {
    const ir = review.items[g.code]
    return !!ir?.seen && !ir.flag
  })

  const row = (c: CheckItem) => {
    const ir = review.items[c.code]
    const status = rowStatus(ir)
    const sel = c.code === selectedCode
    const flagged = !!ir?.flag
    return (
      <div key={c.code} className={`check-row ${sel ? 'on' : ''}`} onClick={() => onSelect(c.code)}>
        <span className={`check-dot ${status}`}>{DOT_GLYPH[status]}</span>
        <div className="check-main">
          <div className="check-label">{c.label}</div>
          {c.kind === 'value' && (
            <div className="check-sub">Bảng kê: {c.reference}</div>
          )}
          {flagged && sel && (
            <div className="flag-editor" onClick={e => e.stopPropagation()}>
              <div className="flag-reasons">
                {FLAG_REASONS.map(rs => (
                  <button key={rs}
                    className={ir!.flag!.reason === rs ? 'on' : ''}
                    onClick={() => onToggleFlag(c.code, { ...ir!.flag!, reason: rs })}>{rs}</button>
                ))}
              </div>
              <input className="flag-note" placeholder="Ghi chú (tuỳ chọn)"
                value={ir!.flag!.note}
                onChange={e => onToggleFlag(c.code, { ...ir!.flag!, note: e.target.value })} />
            </div>
          )}
        </div>
        <button className={`flag-btn ${flagged ? 'on' : ''}`}
          title="Đánh dấu cần gửi lại"
          onClick={e => {
            e.stopPropagation()
            onToggleFlag(c.code, flagged ? null : { reason: '', note: '' })
          }}>{flagged ? 'Bỏ đánh dấu' : '⚑ Đánh dấu'}</button>
      </div>
    )
  }

  return (
    <aside className="checklist">
      <div className="checklist-head">
        <span>Danh sách kiểm tra</span>
        <span className="seen-progress">{seen}/{total} đã xem</span>
        <div className="mini-bar"><i style={{ width: `${pct}%` }} /></div>
      </div>

      <div className="precond">
        <div className="precond-head">
          <span>Điều kiện tiên quyết</span>
          {allGatesOk && <span className="precond-badge">Đủ điều kiện</span>}
        </div>
        {gates.map(row)}
      </div>

      <div className="detail-sec">
        <div className="detail-sec-head">Kiểm tra chi tiết</div>
        {detail.map(row)}
      </div>
    </aside>
  )
}
