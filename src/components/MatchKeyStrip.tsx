import type { MatchedBy, Identity } from '../upload/api'

interface Props { matchedBy: MatchedBy; ocr: Identity; roster: Identity | null }

const BADGE: Record<MatchedBy, { label: string; cls: string }> = {
  cccd: { label: 'Khớp theo CCCD', cls: 'ok' },
  name: { label: 'Khớp theo tên', cls: 'warn' },
  unmatched: { label: 'Chưa khớp bảng kê', cls: 'bad' },
  'no-roster': { label: 'Không có bảng kê', cls: 'muted' },
}

export default function MatchKeyStrip({ matchedBy, ocr, roster }: Props) {
  const badge = BADGE[matchedBy]
  const cccdMismatch = !!roster && ocr.cccd !== roster.cccd
  const nameMismatch = !!roster && ocr.name.toUpperCase() !== roster.name.toUpperCase()
  return (
    <div className="matchkey">
      <span className={`match-badge ${badge.cls}`}>{badge.label}</span>
      {roster && (
        <table className="match-strip">
          <thead><tr><th></th><th>Từ chứng từ</th><th>Từ bảng kê</th></tr></thead>
          <tbody>
            <tr className={cccdMismatch ? 'diff' : ''}>
              <td>CCCD</td><td>{ocr.cccd || '—'}</td><td>{roster.cccd || '—'}</td>
            </tr>
            <tr className={nameMismatch ? 'diff' : ''}>
              <td>Tên</td><td>{ocr.name || '—'}</td><td>{roster.name || '—'}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  )
}
