// Row model for the packet TABLE (ver 2 §2.2). The card grid showed a name, a
// page range and a review badge — enough to navigate, not enough to triage. A
// table earns its place only if its columns discriminate between packets, which
// is the defect that sank ver1's table: 24 of 25 rows read identically there.
//
// So each column here is a different axis, and each comes from data the server
// already computes rather than from anything derived twice:
//   Kết quả AI  — the engine's own rollup (`aiStatus`), identical to the one the
//                 25-criterion matrix shows for the same packet
//   Chứng từ    — document completeness as the engine sees it (`documents`)
//   Cam kết thuế— presence of a bản cam kết (`hasCommitment`)
//   Kết quả FA  — what the REVIEWER concluded (`packetDashboardStatus`)
//
// The AI column keeps all six engine statuses rather than collapsing to
// pass/review/fail. Collapsing hides a real distinction: on the July batch 22
// packets are `no` and 6 are `missing`, and a missing document is a different
// job for the reviewer than a value that disagrees. The design mock folded
// `missing` into "Không khớp" and its own "Thiếu / cần review" counter then
// never counted a single Thiếu case.
import type { PacketMeta, SummaryStatus } from '../upload/api'
import { SUMMARY_STATUS_PRESENTATION } from './summaryTab'
import {
  PACKET_DASHBOARD_LABELS,
  packetDashboardStatus,
  type PacketDashboardStatus,
} from './packetDashboard'

export interface PacketRow {
  index: number
  stt: string
  name: string
  /** null when the engine had no roster row to compare against. */
  ai: SummaryStatus | null
  aiLabel: string
  aiTone: string
  documents: { span: number; missing: string[] } | null
  documentsComplete: boolean | null
  /** e.g. "Đầy đủ (6/6)" or "Thiếu (5/6)". Empty when unknown. */
  documentsLabel: string
  hasCommitment: boolean | null
  fa: PacketDashboardStatus
  faLabel: string
  pages: [number, number]
}

/** The unmatched-packet placeholder, so a row is never blank. */
export const NO_NAME = 'chưa khớp bảng kê'

/**
 * The name-fallback chain for a packet: roster name, then the packet's own
 * name, then the OCR name, then the placeholder. This is the single
 * definition — both this table's rows and the CCCD review screen call it,
 * so the two cannot silently disagree about what a packet is called.
 */
export function packetDisplayName(packet: PacketMeta): string {
  return packet.rosterIdentity?.name
    || packet.name
    || packet.ocrIdentity?.name
    || NO_NAME
}

export function packetRow(packet: PacketMeta): PacketRow {
  const ai = packet.aiStatus ?? null
  const presentation = ai ? SUMMARY_STATUS_PRESENTATION[ai] : null
  const documents = packet.documents ?? null
  const complete = documents ? documents.missing.length === 0 : null
  const fa = packetDashboardStatus(packet)
  return {
    index: packet.index,
    stt: String(packet.index + 1).padStart(2, '0'),
    name: packetDisplayName(packet),
    ai,
    aiLabel: presentation ? presentation.label : 'Chưa đối chiếu được',
    aiTone: presentation ? presentation.tone : 'muted',
    documents,
    documentsComplete: complete,
    documentsLabel: documentsLabel(documents),
    hasCommitment: packet.hasCommitment ?? null,
    fa,
    faLabel: PACKET_DASHBOARD_LABELS[fa],
    pages: packet.pages,
  }
}

export function documentsLabel(
  documents: { span: number; missing: string[] } | null,
): string {
  if (!documents || !documents.span) return ''
  const present = documents.span - documents.missing.length
  return documents.missing.length === 0
    ? `Đầy đủ (${present}/${documents.span})`
    : `Thiếu (${present}/${documents.span})`
}

export function packetRows(packets: PacketMeta[]): PacketRow[] {
  return packets.map(packetRow)
}

// --- filtering ---------------------------------------------------------------

export interface PacketTableFilters {
  /** Free text over the name. */
  q: string
  /** '' = any. */
  ai: SummaryStatus | ''
  /** '' = any, else complete/incomplete documents. */
  documents: '' | 'complete' | 'missing'
  /** '' = any. */
  fa: PacketDashboardStatus | ''
  /** '' = any. */
  commitment: '' | 'yes' | 'no'
}

export const NO_FILTERS: PacketTableFilters = {
  q: '', ai: '', documents: '', fa: '', commitment: '',
}

export function filterRows(
  rows: PacketRow[],
  filters: PacketTableFilters,
): PacketRow[] {
  const q = filters.q.trim().toLowerCase()
  return rows.filter(row => {
    if (q && !row.name.toLowerCase().includes(q)) return false
    if (filters.ai && row.ai !== filters.ai) return false
    if (filters.fa && row.fa !== filters.fa) return false
    if (filters.documents === 'complete' && row.documentsComplete !== true) return false
    if (filters.documents === 'missing' && row.documentsComplete !== false) return false
    if (filters.commitment === 'yes' && row.hasCommitment !== true) return false
    if (filters.commitment === 'no' && row.hasCommitment !== false) return false
    return true
  })
}

/** Whether any filter is narrowing the list — drives the "clear" affordance. */
export function isFiltering(filters: PacketTableFilters): boolean {
  return !!(filters.q.trim() || filters.ai || filters.documents || filters.fa
            || filters.commitment)
}

// --- the headline counters ---------------------------------------------------

/**
 * One counter per engine status, plus the total.
 *
 * By status rather than by a collapsed good/bad, for the reason in the header:
 * a counter labelled one thing while excluding cases that belong to it is worse
 * than no counter. Every packet lands in exactly one bucket, so the buckets
 * always sum to `total` — which is what makes them safe to use as filters.
 */
export function statusCounts(rows: PacketRow[]): {
  total: number
  byStatus: Record<SummaryStatus, number>
  unrated: number
} {
  const byStatus: Record<SummaryStatus, number> = {
    ok: 0, no: 0, rv: 0, missing: 0, pending: 0, na: 0,
  }
  let unrated = 0
  for (const row of rows) {
    if (row.ai) byStatus[row.ai] += 1
    else unrated += 1
  }
  return { total: rows.length, byStatus, unrated }
}

/**
 * The statuses worth showing a counter for, worst first, skipping any that no
 * packet has — a row of zeroes is noise, and the order puts the work first.
 */
export const COUNTER_ORDER: SummaryStatus[] = [
  'no', 'missing', 'rv', 'pending', 'ok', 'na',
]

export function visibleCounters(
  rows: PacketRow[],
): Array<{ status: SummaryStatus; label: string; tone: string; count: number }> {
  const { byStatus } = statusCounts(rows)
  return COUNTER_ORDER
    .filter(status => byStatus[status] > 0)
    .map(status => ({
      status,
      label: SUMMARY_STATUS_PRESENTATION[status].label,
      tone: SUMMARY_STATUS_PRESENTATION[status].tone,
      count: byStatus[status],
    }))
}
