import type { CheckItem } from '../ctv/types'
import type { PacketReview, FieldFlag } from '../upload/api'

interface Props {
  checks: CheckItem[]
  review: PacketReview
  selectedCode: string
  onSelect: (code: string) => void
  onToggleFlag: (code: string, flag: FieldFlag | null) => void
}

type RowStatus = 'ok' | 'bad' | 'review' | 'flag'

function rowStatus(c: CheckItem, ir?: { seen: boolean; flag: FieldFlag | null }): RowStatus {
  if (ir?.flag) return 'flag'
  if (c.kind === 'confirm') return ir?.seen ? 'ok' : 'review'
  // value / identity: driven by the autostatus hint
  return c.autostatus === 'match' ? 'ok' : c.autostatus === 'mismatch' ? 'bad' : 'review'
}

const DOT_GLYPH: Record<RowStatus, string> = { ok: '✓', bad: '✗', review: '●', flag: '⚑' }

// Right-side status word. Gates never actually surface "bad" (their kind is always
// confirm/identity -- a value mismatch can't happen -- see server/checklist.py) but the
// map stays total so the lookup below never needs a fallback branch. Detail splits by
// kind: a value compare ("Khớp"/"Lệch") vs a plain sighted confirm ("Đạt").
const GATE_WORD: Record<RowStatus, string> = { ok: 'Đạt', bad: 'Cần xem', review: 'Cần xem', flag: 'Đã đánh dấu' }
const DETAIL_VALUE_WORD: Record<RowStatus, string> = { ok: 'Khớp', bad: 'Lệch', review: 'Cần xem', flag: 'Đã đánh dấu' }
const DETAIL_CONFIRM_WORD: Record<RowStatus, string> = { ok: 'Đạt', bad: 'Cần xem', review: 'Cần xem', flag: 'Đã đánh dấu' }

function statusWord(c: CheckItem, status: RowStatus): string {
  if (c.tier === 'gate') return GATE_WORD[status]
  return c.kind === 'value' ? DETAIL_VALUE_WORD[status] : DETAIL_CONFIRM_WORD[status]
}

// The little match hint next to "Bảng kê: {reference}" on value rows always reflects the
// raw auto-compare, independent of a reviewer flag -- .match-hint only has ok/bad/review
// variants (no "flag" one), unlike the flag-aware .check-status word above.
function valueHintStatus(c: CheckItem): 'ok' | 'bad' | 'review' {
  return c.autostatus === 'match' ? 'ok' : c.autostatus === 'mismatch' ? 'bad' : 'review'
}

const FLAG_REASONS = ['sai', 'thiếu', 'mờ, không đọc được']

export default function ChecklistPanel({ checks, review, selectedCode, onSelect, onToggleFlag }: Props) {
  const gates = checks.filter(c => c.tier === 'gate')
  const detail = checks.filter(c => c.tier === 'detail')
  const total = checks.length
  const seen = checks.filter(c => review.items[c.code]?.seen).length
  const pct = total ? Math.round((seen / total) * 100) : 0
  const allGatesOk = gates.every(g => rowStatus(g, review.items[g.code]) === 'ok')

  const row = (c: CheckItem) => {
    const ir = review.items[c.code]
    const status = rowStatus(c, ir)
    const sel = c.code === selectedCode
    const flagged = !!ir?.flag
    const hint = valueHintStatus(c)
    return (
      <div key={c.code} className={`check-row ${sel ? 'on' : ''}`} onClick={() => onSelect(c.code)}>
        <span className={`check-dot ${status}`}>{DOT_GLYPH[status]}</span>
        <div className="check-main">
          <div className="check-label">{c.label}</div>
          {c.kind === 'value' && (
            <div className="check-sub">
              Bảng kê: {c.reference} · <span className={`match-hint ${hint}`}>{DETAIL_VALUE_WORD[hint]}</span>
            </div>
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
        <span className="check-status">{statusWord(c, status)}</span>
        <button className={`flag-btn ${flagged ? 'on' : ''}`}
          title="Đánh dấu cần gửi lại"
          onClick={e => {
            e.stopPropagation()
            onToggleFlag(c.code, flagged ? null : { reason: '', note: '' })
          }}>{flagged ? 'Đã đánh dấu' : '⚑ Đánh dấu'}</button>
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
