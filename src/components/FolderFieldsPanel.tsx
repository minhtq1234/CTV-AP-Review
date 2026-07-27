import type { RankedCtv } from '../ctv/checks'
import type { PacketReview, FieldFlag } from '../upload/api'
import { PACKET_REJECTION_OPTIONS } from '../logic/packetRejection'
import type { ReviewSelection } from '../logic/reviewSelection'
import { formatRosterValue } from '../logic/reviewValue'

interface Props {
  ranked: RankedCtv[]
  selection: ReviewSelection
  onSelectOverview: () => void
  onSelectField: (key: string) => void
  review: PacketReview
  onToggleFlag: (fieldKey: string, flag: FieldFlag | null) => void
  onOpenPacketRejection: () => void
}

export default function FolderFieldsPanel({
  ranked,
  selection,
  onSelectOverview,
  onSelectField,
  review,
  onToggleFlag,
  onOpenPacketRejection,
}: Props) {
  const total = ranked.length
  const seen = ranked.filter(r => review.fields[r.field.key]?.seen).length
  return (
    <aside className="fields-pane">
      <div className="fields-summary">
        <span>{ranked.length} mục kiểm tra</span>
        <span className="seen-progress">{seen}/{total} đã xem</span>
      </div>
      <section
        className={`overview-row${selection.kind === 'overview' ? ' sel' : ''}`}
        data-review-selection={selection.kind === 'overview' ? 'overview' : undefined}
        onClick={onSelectOverview}
      >
        <div className="overview-row-head">
          <div>
            <strong>Tổng quan</strong>
            <span>Xem nhanh toàn bộ chứng từ</span>
          </div>
          {!review.rejection && (
            <button
              type="button"
              className="overview-rejection-open"
              onClick={event => {
                event.stopPropagation()
                onSelectOverview()
                onOpenPacketRejection()
              }}
            >
              Từ chối hồ sơ
            </button>
          )}
        </div>
        {review.rejection && (
          <div className="packet-rejection-summary" aria-label="Đã từ chối">
            <div className="packet-rejection-summary-head">
              <strong>Đã từ chối</strong>
              <button
                type="button"
                onClick={event => {
                  event.stopPropagation()
                  onSelectOverview()
                  onOpenPacketRejection()
                }}
              >
                Sửa lý do
              </button>
            </div>
            <ul>
              {PACKET_REJECTION_OPTIONS
                .filter(option => review.rejection?.reasons.includes(option.value))
                .map(option => <li key={option.value}>{option.label}</li>)}
            </ul>
            {review.rejection.note && (
              <p className="packet-rejection-summary-note">
                {review.rejection.note}
              </p>
            )}
          </div>
        )}
      </section>
      {ranked.map(r => {
        const sel = selection.kind === 'field'
          && r.field.key === selection.key
        const viewed = !!review.fields[r.field.key]?.seen
        return (
          <div key={r.field.key} className={`cfield ${sel ? 'sel' : ''}`} onClick={() => onSelectField(r.field.key)}>
            <div className="cfield-head">
              <span className={`view-status ${viewed ? 'viewed' : 'not-viewed'}`}>
                {viewed ? 'Đã xem' : 'Chưa xem'}
              </span>
              <span className="flabel">{r.field.label}</span>
              <span className="ftag">{r.field.group}</span>
              <button className={`flag-btn ${review.fields[r.field.key]?.flag ? 'on' : ''}`}
                title="Đánh dấu cần gửi lại (F)"
                onClick={e => {
                  e.stopPropagation()
                  onSelectField(r.field.key)
                  const cur = review.fields[r.field.key]?.flag
                  onToggleFlag(r.field.key, cur ? null : { reason: '', note: '' })
                }}>
                {review.fields[r.field.key]?.flag ? 'Bỏ đánh dấu' : '⚑ Đánh dấu'}
              </button>
            </div>
            <div className="cfield-exp">Kê khai (Excel): <b>{formatRosterValue(r.field)}</b></div>
            {review.fields[r.field.key]?.flag && sel && (
              <div className="flag-editor" onClick={e => e.stopPropagation()}>
                <div className="flag-reasons">
                  {['sai', 'thiếu', 'mờ, không đọc được'].map(rs => (
                    <button key={rs}
                      className={review.fields[r.field.key]!.flag!.reason === rs ? 'on' : ''}
                      onClick={() => onToggleFlag(r.field.key,
                        { ...review.fields[r.field.key]!.flag!, reason: rs })}>{rs}</button>
                  ))}
                </div>
                <input className="flag-note" placeholder="Ghi chú (tuỳ chọn)"
                  value={review.fields[r.field.key]!.flag!.note}
                  onChange={e => onToggleFlag(r.field.key,
                    { ...review.fields[r.field.key]!.flag!, note: e.target.value })} />
              </div>
            )}
          </div>
        )
      })}
    </aside>
  )
}
