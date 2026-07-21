import type { JobResult, PacketSummary } from '../upload/api'

interface Props {
  result: JobResult
  onOpen: (index: number) => void
  onReset: () => void
}

// The in-app mirror of the splitter's own report.html: a summary banner + a grid
// of packet cards (wording mirrors splitter/detect_packets.py's build_report_html).
export default function SplitResultScreen({ result, onOpen, onReset }: Props) {
  const { summary, packets } = result
  const rosterTxt = summary.roster_n == null ? '—' : String(summary.roster_n)
  const aligned =
    summary.roster_n == null
      ? '(không có bảng kê để đối chiếu)'
      : summary.roster_n === summary.found
        ? '✓ khớp'
        : '⚠ lệch số lượng'
  const amber = packets.filter(p => p.confidence === 'amber').length
  const mergedTxt = summary.auto_merged
    ? ` · ${summary.auto_merged} ranh giới gộp tự động — cần xác nhận`
    : ''

  return (
    <div className="split-result">
      <div className="banner result-banner">
        <b>Kết quả tách hồ sơ</b>
        <span>
          {summary.found} / {rosterTxt} gói (tìm thấy / bảng kê) · {aligned} ·{' '}
          {summary.matched}/{summary.found} đã khớp tên · {amber} gói cần xem lại
          {mergedTxt}
        </span>
      </div>

      <div className="packet-grid">
        {packets.map(p => (
          <PacketCard key={p.index} p={p} onOpen={onOpen} />
        ))}
      </div>

      <div className="result-actions">
        <button className="btn" onClick={onReset}>Tải hồ sơ khác</button>
      </div>
    </div>
  )
}

function PacketCard({ p, onOpen }: { p: PacketSummary; onOpen: (index: number) => void }) {
  const [start, end] = p.pages
  return (
    <button className={`packet-card ${p.confidence}`} onClick={() => onOpen(p.index)}>
      <div className="packet-card-head">
        <span className={`conf-dot ${p.confidence}`} />
        <span className="packet-name">{p.name || 'chưa khớp tên'}</span>
      </div>
      <div className="packet-range">p{start + 1}–{end + 1} · {p.n_pages} trang</div>
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
