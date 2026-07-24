import type { DocRecap } from '../ctv/types'

interface Props {
  loading: boolean
  error: string | null
  recap: DocRecap | null
  docLabel: string
  onClose: () => void
}

// The AI-recap popover: Tóm tắt (bullets) + Nhận định (tentative conclusion) + a
// footer disclaimer. Pure display — it never marks or flags a check.
export default function RecapPopover({ loading, error, recap, docLabel, onClose }: Props) {
  const ready = !!recap && !loading && !error
  return (
    <div className="recap-pop" role="dialog" aria-label="AI tóm tắt tài liệu">
      <div className="recap-pop-head">
        <span className="recap-pop-title">✨ AI tóm tắt — {docLabel}</span>
        <button className="recap-pop-x" onClick={onClose} aria-label="Đóng">×</button>
      </div>
      <div className="recap-pop-body">
        {loading && <div className="recap-loading">Đang đọc tài liệu…</div>}
        {error && !loading && <div className="recap-error">{error}</div>}
        {ready && (
          <>
            <div className="recap-sec-h">Tóm tắt</div>
            <ul className="recap-bullets">
              {recap!.bullets.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
            <div className="recap-sec-h">Nhận định</div>
            <p className="recap-nhandinh">{recap!.nhanDinh}</p>
          </>
        )}
      </div>
      {ready && <div className="recap-pop-foot">{recap!.disclaimer}</div>}
    </div>
  )
}
