import type { CaseDetail as CaseDetailT, PacketMeta } from '../upload/api'
import { caseProgressLabel, packetNeedsResubmit } from '../upload/api'
import { packetStatus, PACKET_STATUS_LABEL } from '../logic/review'
import { formatCccdSummary } from '../upload/cccd'

interface Props {
  detail: CaseDetailT
  onOpenPacket: (index: number) => void
  onBack: () => void
  onExport: () => void
}

// The case-detail screen: header (name + case status + review progress) over the
// same packet-card grid the splitter's own result view uses (see SplitResultScreen),
// with each card now also carrying its derived review status badge.
export default function CaseDetail({ detail, onOpenPacket, onBack, onExport }: Props) {
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

      {detail.cccdName && detail.cccdSummary && (
        <div className={`cccd-summary ${detail.cccdSummary.status}`}>
          {formatCccdSummary(detail.cccdSummary)}
        </div>
      )}

      <div className="case-summary">
        <span>{packets.length} gói · {packets.filter(packetNeedsResubmit).length} cần gửi lại · {packets.reduce((n, p) => n + Object.values(p.review?.items ?? {}).filter(f => f.flag).length, 0)} trường có vấn đề</span>
        <button className="btn primary" onClick={onExport}>Xuất báo cáo gửi lại</button>
      </div>

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
  const status = packetStatus(p)
  return (
    <button className={`packet-card ${p.confidence}`} onClick={() => onOpen(p.index)}>
      <div className="packet-card-head">
        <span className={`conf-dot ${p.confidence}`} />
        <span className="packet-name">{p.name || 'chưa khớp tên'}</span>
      </div>
      <div className="packet-range">
        p{start + 1}–{end + 1}{p.n_pages ? ` · ${p.n_pages} trang` : ''}
      </div>
      <div className={`decision-badge ${status}`}>{PACKET_STATUS_LABEL[status]}</div>
      {p.matchedBy === 'name' && <span className="card-match warn">khớp theo tên</span>}
      {p.matchedBy === 'unmatched' && <span className="card-match bad">chưa khớp bảng kê</span>}
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
