import { useState } from 'react'
import type { CaseDetail as CaseDetailT, PacketMeta } from '../upload/api'
import { caseProgressLabel } from '../upload/api'
import {
  attentionReasons,
  boundaryNote,
  findingsNote,
  filterPackets,
  PACKET_DASHBOARD_LABELS,
  packetDashboardCounts,
  packetDashboardStatus,
  packetStatusSummary,
  prioritizeAttention,
  type PacketDashboardFilter,
} from '../logic/packetDashboard'
import PacketTable from './PacketTable'
import { packetDisplayName } from '../logic/packetTable'
import { formatCccdSummary } from '../upload/cccd'
import SummaryTab from './SummaryTab'
import PacketDocsDialog from './PacketDocsDialog'

interface Props {
  detail: CaseDetailT
  onOpenPacket: (index: number) => void
  onBack: () => void
  onExport: () => void
  /** Which tab to land on. The criteria matrix's roster-level cell sends the
   *  reviewer here to check the bảng kê, and that check lives on Tổng hợp. */
  initialTab?: CaseTab
  /** Ver 3: back to the CCCD review step. Absent in contexts without one. */
  onOpenCccd?: () => void
}

// The case-detail screen: header (name + case status + review progress) over the
// same packet-card grid the splitter's own result view uses (see SplitResultScreen),
// with each card now also carrying its derived review status badge.
export default function CaseDetail({
  detail, onOpenPacket, onBack, onExport, onOpenCccd, initialTab = 'packets',
}: Props) {
  const { summary, packets } = detail
  const [filter, setFilter] = useState<PacketDashboardFilter>('all')
  const [attentionFirst, setAttentionFirst] = useState(false)
  const [tab, setTab] = useState<CaseTab>(SHOW_SUMMARY_TAB ? initialTab : 'packets')
  // The packet a "Xem chứng từ" click asked to preview -- null when the
  // dialog is closed. Kept here (not in PacketDashboardView) because opening
  // the full reviewer from inside the dialog needs the same onOpenPacket a
  // row click uses, and that prop lives on this component.
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const previewPacket = previewIndex !== null
    ? packets.find(p => p.index === previewIndex) ?? null
    : null
  // Continuing into the full reviewer from the dialog is still a navigation
  // — close the popup on the way out rather than leaving it to a stale
  // unmount, so it is never still open if the reviewer comes back here.
  const openPacketFromPreview = (index: number) => {
    setPreviewIndex(null)
    onOpenPacket(index)
  }
  const rosterTxt = summary?.roster_n == null ? '—' : String(summary.roster_n)
  const mergedTxt = summary?.auto_merged
    ? ` · ${summary.auto_merged} ranh giới gộp tự động — cần xác nhận`
    : ''
  const boundaryTxt = summary ? boundaryNote(summary) : ''
  // Two counts, deliberately apart: `cần gửi lại` is what a person decided, and
  // the engine's own findings are candidates to look at.
  const findingsTxt = findingsNote(detail.progress)

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
          {boundaryTxt && <span className="case-boundary-note">{boundaryTxt}</span>}
        </div>
      )}

      {detail.cccdName && detail.cccdSummary && (
        <div className={`cccd-summary ${detail.cccdSummary.status}`}>
          {formatCccdSummary(detail.cccdSummary)}
          {onOpenCccd && (
            <button type="button" className="cccd-summary-link" onClick={onOpenCccd}>
              Xem thẻ CCCD
            </button>
          )}
        </div>
      )}

      {SHOW_SUMMARY_TAB && (
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
      )}

      {tab === 'summary' ? (
        <SummaryTab caseId={detail.id} />
      ) : (
        <>
      <div className="case-summary">
        <span>
          {packets.length} gói
          {findingsTxt && <> · {findingsTxt}</>}
          {' '}· {packets.reduce((n, p) => n + Object.values(p.review?.fields ?? {}).filter(f => f.flag).length, 0)} trường có vấn đề
        </span>
        <button className="btn primary" onClick={onExport}>Xuất báo cáo gửi lại</button>
      </div>

      <PacketDashboardView
        packets={packets}
        filter={filter}
        attentionFirst={attentionFirst}
        onFilter={setFilter}
        onAttentionFirst={setAttentionFirst}
        onOpenPacket={onOpenPacket}
        onPreviewDocs={setPreviewIndex}
      />
        </>
      )}

      {previewIndex !== null && previewPacket && (
        <PacketDocsDialog
          caseId={detail.id}
          packetIndex={previewIndex}
          packetName={packetDisplayName(previewPacket)}
          onClose={() => setPreviewIndex(null)}
          onOpenPacket={openPacketFromPreview}
        />
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

/**
 * Tổng hợp is hidden for now, at the reviewer's request. Landing on it
 * unexpectedly was worse than not having it: UploadFlow's `detailTab` was
 * sticky, so one Bảng Kê Thu Mua jump made every later back-out-of-a-packet
 * land here instead of on the packet list.
 *
 * Flip this to true to bring it back -- SummaryTab, the five roster-level
 * criteria, `GET /api/cases/{id}/summary` and their tests are all still here
 * and still passing. Restoring the matrix's jump to it needs `onShowSummary`
 * wired again in UploadFlow, and `detailTab` cleared once consumed.
 */
const SHOW_SUMMARY_TAB = false

export interface PacketDashboardViewProps {
  packets: PacketMeta[]
  filter: PacketDashboardFilter
  attentionFirst: boolean
  onFilter: (filter: PacketDashboardFilter) => void
  onAttentionFirst: (active: boolean) => void
  onOpenPacket: (index: number) => void
  /** Optional: see PacketTable's own prop of the same name. */
  onPreviewDocs?: (index: number) => void
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
  onPreviewDocs,
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
        <PacketTable packets={visible} onOpenPacket={onOpenPacket} onPreviewDocs={onPreviewDocs} />
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
