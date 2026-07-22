import type { CaseDetail as CaseDetailT, PacketMeta } from '../upload/api'
import { caseProgressLabel, decisionBadge } from '../upload/api'

interface Props {
  detail: CaseDetailT
  onOpenPacket: (index: number) => void
  onBack: () => void
}

// The case-detail screen: header (name + case status + review progress) over the
// same packet-card grid the splitter's own result view uses (see SplitResultScreen),
// with each card now also carrying its persisted decision badge.
export default function CaseDetail({ detail, onOpenPacket, onBack }: Props) {
  const { summary, packets } = detail
  const rosterTxt = summary?.roster_n == null ? '—' : String(summary.roster_n)
  const mergedTxt = summary?.auto_merged
    ? ` · ${summary.auto_merged} ranh giới gộp tự động — cần xác nhận`
    : ''

  return (
    <div className="split-result">
      <div className="case-detail-head">
        <button className="btn" onClick={onBack}>← Danh sách hồ sơ</button>
        <h2>{detail.name}</h2>
      </div>

      {detail.status === 'error' && (
        <div className="banner result-banner case-error-banner">
          <b>Lỗi xử lý</b>
          <span>{detail.error ?? 'Không rõ nguyên nhân.'}</span>
        </div>
      )}

      {summary && (
        <div className="banner result-banner">
          <b>Kết quả tách hồ sơ</b>
          <span>
            {summary.found} / {rosterTxt} gói (tìm thấy / bảng kê) ·{' '}
            {summary.matched}/{summary.found} đã khớp tên · {caseProgressLabel(detail.progress)}
            {mergedTxt}
          </span>
        </div>
      )}

      <div className="packet-grid">
        {packets.map(p => (
          <PacketCard key={p.index} p={p} onOpen={onOpenPacket} />
        ))}
      </div>
    </div>
  )
}

function PacketCard({ p, onOpen }: { p: PacketMeta; onOpen: (index: number) => void }) {
  const [start, end] = p.pages
  return (
    <button className={`packet-card ${p.confidence}`} onClick={() => onOpen(p.index)}>
      <div className="packet-card-head">
        <span className={`conf-dot ${p.confidence}`} />
        <span className="packet-name">{p.name || 'chưa khớp tên'}</span>
      </div>
      <div className="packet-range">
        p{start + 1}–{end + 1}{p.n_pages ? ` · ${p.n_pages} trang` : ''}
      </div>
      <div className={`decision-badge ${p.decision}`}>{decisionBadge(p.decision)}</div>
      {p.flags.length > 0 && (
        <div className="packet-flags">
          {p.flags.map(f => (
            <span key={f} className="flag-chip">{f}</span>
          ))}
        </div>
      )}
    </button>
  )
}
