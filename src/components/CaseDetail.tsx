import { useState } from 'react'
import type { CaseDetail as CaseDetailT, PacketMeta } from '../upload/api'
import { caseProgressLabel, packetNeedsResubmit } from '../upload/api'
import {
  attentionReasons,
  filterPackets,
  PACKET_DASHBOARD_LABELS,
  packetDashboardCounts,
  packetDashboardStatus,
  packetFlagCount,
  packetSeenCount,
  prioritizeAttention,
  type PacketDashboardFilter,
  type PacketDashboardStatus,
} from '../logic/packetDashboard'
import { PACKET_REJECTION_OPTIONS } from '../logic/packetRejection'
import { formatCccdSummary } from '../upload/cccd'
import SummaryTab from './SummaryTab'

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
  const [filter, setFilter] = useState<PacketDashboardFilter>('all')
  const [attentionFirst, setAttentionFirst] = useState(false)
  const [tab, setTab] = useState<CaseTab>('packets')
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

      <div className="case-tabs" role="tablist" aria-label="Chế độ xem hồ sơ">
        {CASE_TABS.map(option => (
          <button
            key={option.value}
            type="button"
            role="tab"
            className={`case-tab${tab === option.value ? ' active' : ''}`}
            aria-selected={tab === option.value}
            onClick={() => setTab(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {tab === 'summary' ? (
        <SummaryTab caseId={detail.id} />
      ) : (
        <>
      <div className="case-summary">
        <span>{packets.length} gói · {packets.filter(packetNeedsResubmit).length} cần gửi lại · {packets.reduce((n, p) => n + Object.values(p.review?.fields ?? {}).filter(f => f.flag).length, 0)} trường có vấn đề</span>
        <button className="btn primary" onClick={onExport}>Xuất báo cáo gửi lại</button>
      </div>

      <PacketDashboardView
        packets={packets}
        filter={filter}
        attentionFirst={attentionFirst}
        onFilter={setFilter}
        onAttentionFirst={setAttentionFirst}
        onOpenPacket={onOpenPacket}
      />
        </>
      )}
    </div>
  )
}

// Two views over one hồ sơ: the per-CTV packets, and the five criteria that
// apply to the whole bảng kê and so belong to no packet.
export type CaseTab = 'packets' | 'summary'

const CASE_TABS: Array<{ value: CaseTab; label: string }> = [
  { value: 'packets', label: 'Gói hồ sơ' },
  { value: 'summary', label: 'Tổng hợp' },
]

export interface PacketDashboardViewProps {
  packets: PacketMeta[]
  filter: PacketDashboardFilter
  attentionFirst: boolean
  onFilter: (filter: PacketDashboardFilter) => void
  onAttentionFirst: (active: boolean) => void
  onOpenPacket: (index: number) => void
}

const FILTERS: Array<{
  value: PacketDashboardFilter
  label: string
}> = [
  { value: 'all', label: 'Tất cả' },
  { value: 'unseen', label: PACKET_DASHBOARD_LABELS.unseen },
  { value: 'reviewing', label: PACKET_DASHBOARD_LABELS.reviewing },
  { value: 'completed', label: PACKET_DASHBOARD_LABELS.completed },
  { value: 'flagged', label: PACKET_DASHBOARD_LABELS.flagged },
]

export function PacketDashboardView({
  packets,
  filter,
  attentionFirst,
  onFilter,
  onAttentionFirst,
  onOpenPacket,
}: PacketDashboardViewProps) {
  const counts = packetDashboardCounts(packets)
  const filtered = filterPackets(packets, filter)
  const visible = attentionFirst ? prioritizeAttention(filtered) : filtered

  return (
    <>
      <div className="packet-dashboard-controls" aria-label="Bộ lọc trạng thái gói hồ sơ">
        <div className="packet-filters">
          {FILTERS.map(option => (
            <button
              key={option.value}
              type="button"
              className={`packet-filter${filter === option.value ? ' active' : ''}`}
              aria-pressed={filter === option.value}
              onClick={() => onFilter(option.value)}
            >
              <span>{option.label}</span>
              <span className="packet-filter-count">
                {option.value === 'all' ? packets.length : counts[option.value]}
              </span>
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`packet-attention-toggle${attentionFirst ? ' active' : ''}`}
          aria-pressed={attentionFirst}
          onClick={() => onAttentionFirst(!attentionFirst)}
        >
          <span className="packet-attention-icon" aria-hidden="true">!</span>
          Cần chú ý trước
        </button>
      </div>

      {visible.length > 0 ? (
        <div className="packet-grid">
          {visible.map(packet => (
            <PacketCard
              key={packet.index}
              packet={packet}
              onOpen={onOpenPacket}
            />
          ))}
        </div>
      ) : (
        <div className="packet-grid-empty">
          Không có gói hồ sơ ở trạng thái này.
        </div>
      )}
    </>
  )
}

export function PacketCard({
  packet,
  onOpen,
}: {
  packet: PacketMeta
  onOpen: (index: number) => void
}) {
  const [start, end] = packet.pages
  const status = packetDashboardStatus(packet)
  const attention = attentionReasons(packet)
  const summary = packetStatusSummary(packet, status)
  const attentionLabel = attention.join(' · ')
  const attentionCopy = attention.length > 1
    ? `${attention[0]} +${attention.length - 1}`
    : attention[0]

  return (
    <button
      className={`packet-card ${status}`}
      onClick={() => onOpen(packet.index)}
    >
      <div className="packet-card-head">
        <span className="packet-status-dot" aria-hidden="true" />
        <span className="packet-name">{packet.name || 'chưa khớp tên'}</span>
      </div>
      <div className="packet-range">
        p{start + 1}–{end + 1}
        {packet.n_pages ? ` · ${packet.n_pages} trang` : ''}
      </div>
      <div className={`decision-badge ${status}`}>
        {PACKET_DASHBOARD_LABELS[status]}
      </div>
      {summary && <div className="packet-status-summary">{summary}</div>}
      {attentionCopy && (
        <div className="packet-attention" title={attentionLabel} aria-label={attentionLabel}>
          <span className="packet-attention-icon" aria-hidden="true">!</span>
          <span>{attentionCopy}</span>
        </div>
      )}
    </button>
  )
}

function packetStatusSummary(
  packet: PacketMeta,
  status: PacketDashboardStatus,
): string | null {
  if (status === 'reviewing') {
    const seen = packetSeenCount(packet)
    return packet.reviewFieldCount > 0
      ? `${seen}/${packet.reviewFieldCount} đã xem`
      : `${seen} trường đã xem`
  }
  if (status !== 'flagged') return null
  if (packet.review.rejection) {
    const selected = new Set(packet.review.rejection.reasons)
    const labels = PACKET_REJECTION_OPTIONS
      .filter(option => selected.has(option.value))
      .map(option => option.label)
    return `Đã từ chối · ${labels.join('; ')}`
  }
  return `${packetFlagCount(packet)} trường đã đánh dấu`
}
