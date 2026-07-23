import type { MatchedBy, Identity } from '../upload/api'

interface Props { matchedBy: MatchedBy; ocr: Identity; roster: Identity | null }

const BADGE: Record<MatchedBy, { label: string; cls: string }> = {
  cccd: { label: 'Danh tính khớp', cls: 'ok' },
  name: { label: 'Khớp theo tên', cls: 'warn' },
  unmatched: { label: 'Chưa khớp bảng kê', cls: 'bad' },
  'no-roster': { label: 'Không có bảng kê', cls: 'muted' },
}

export default function MatchKeyStrip({ matchedBy, ocr, roster }: Props) {
  const badge = BADGE[matchedBy]
  // Weak match = the identity claim is in doubt (name-only or no match at all).
  // That's when the reviewer needs the OCR-vs-roster detail; a clean CCCD hit
  // or a missing roster row stays a quiet pill.
  const weak = matchedBy === 'name' || matchedBy === 'unmatched'
  const cccdMismatch = !!roster && ocr.cccd !== roster.cccd
  const nameMismatch = !!roster && ocr.name.toUpperCase() !== roster.name.toUpperCase()
  return (
    <div className="matchkey">
      <span className={`match-badge ${badge.cls}`}>
        <span className="match-badge-icon" aria-hidden="true">🛡</span>
        {badge.label}
      </span>
      {weak && roster && (
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
