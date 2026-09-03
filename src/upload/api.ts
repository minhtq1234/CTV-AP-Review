// Client for the isolated v1 backend. Port 8002 keeps its field-keyed case data
// separate from the v2 checklist backend on port 8000.
// upload a scanned PDF (+ optional roster) as a durable **case**, list/inspect
// cases, fetch a packet's manifest as a CtvFolder the existing reviewer already
// knows how to render, and persist per-packet duyệt/từ chối decisions.
import type { CtvFolder } from '../ctv/types'
import type { Bbox } from '../types'

export const API_BASE = 'http://127.0.0.1:8002'

export type Stage = 'queued' | 'splitting' | 'ocr' | 'done' | 'error' | string

export interface Progress {
  stage: Stage
  done: number
  total: number
  detail: string
}

// ---------------------------------------------------------------------------
// Case types (mirror server/cases.py's case.json shape 1:1 — see the spec's
// data model in docs/superpowers/specs/2026-07-13-case-management-design.md).
// ---------------------------------------------------------------------------

export type CaseState = 'processing' | 'ready' | 'in_review' | 'done' | 'error'

// Strongest key first. `mst` sits between `cccd` and `name` because the
// personal MST is a real identifier, while a name match is the fragile path —
// see server/pipeline.py's `match_roster`.
export type MatchedBy = 'cccd' | 'mst' | 'name' | 'unmatched' | 'no-roster'

export interface Identity {
  cccd: string
  name: string
}

export interface FieldFlag {
  reason: string
  note: string
}

export interface FieldReview {
  seen: boolean
  flag: FieldFlag | null
}

export const PACKET_REJECTION_REASONS = [
  'missing_documents',
  'wrong_template',
  'missing_signature',
] as const

export type PacketRejectionReason = typeof PACKET_REJECTION_REASONS[number]

export interface PacketRejection {
  reasons: PacketRejectionReason[]
  note: string
}

export interface PacketReview {
  done: boolean
  fields: Record<string, FieldReview>
  rejection: PacketRejection | null
  /** Criteria-cell decisions, append-only: `{key: [record, ...]}`. */
  overrides?: Record<string, CriterionDecision[]>
}

export interface CaseProgress {
  done: number
  total: number
  flagged: number
  /** Packets the engine found something in that nobody has decided on. */
  candidates?: number
}

export interface PacketMeta {
  index: number
  name: string | null
  pages: [number, number]
  n_pages?: number
  confidence: 'green' | 'amber'
  flags: string[]
  /** Other packets claiming the same bảng kê row, when flagged duplicate. */
  duplicateOf?: number[]
  labels?: string[]
  matchedBy: MatchedBy
  ocrIdentity: Identity
  rosterIdentity: Identity | null
  review: PacketReview
  reviewFieldCount: number
  /** What the engine found here and nobody has decided on yet. */
  findingCount?: number
  /**
   * The engine's own worst-wins rollup over this packet's criteria — the same
   * `criteria.roll_up` the 25-criterion matrix uses, so a list column and the
   * matrix cannot disagree. Null when the packet matched no bảng kê row: with
   * nothing to compare against, the list must not imply a verdict.
   */
  aiStatus?: SummaryStatus | null
  /**
   * Document completeness as the ENGINE sees it, not against a hand-written
   * required list: `span` is how many documents this packet's criteria actually
   * reach, `missing` names the ones that are not there. Excludes the bảng kê —
   * that is the reference, not something the CTV submits.
   */
  documents?: { span: number; missing: string[] } | null
  /** Whether a bản cam kết thuế is present in the packet. */
  hasCommitment?: boolean | null
}

// The pipeline's split/OCR summary — key names mirror server/pipeline.py's
// `run_pipeline` return value (snake_case, as produced by the real pipeline).
export interface CaseResultSummary {
  found: number
  roster_n: number | null
  matched: number
  auto_merged: number
  /** Packets whose boundary the splitter moved to the page a document starts on. */
  boundaries_snapped?: number
  /** Pages every boundary moved back by; 0 when they were already right, null
   *  when the offsets disagreed and nothing moved. Absent on older cases. */
  boundaries_offset?: number | null
  /** Why nothing moved, when nothing did. */
  boundaries_reason?: string
  /** Packets that took the offset from the others rather than finding it. */
  boundaries_inferred?: number
  /** Boundaries added inside packets that held two CTVs' documents. */
  boundaries_inserted?: number
}

export interface CaseSummary {
  id: string
  name: string
  createdAt: string | null
  status: CaseState
  pdfName: string
  progress: CaseProgress
}

export interface CccdSummary {
  status: 'ready' | 'partial' | 'error'
  candidates: number
  attached: number
  unresolved: number
  errorCode?: string
}

export interface CaseDetail {
  id: string
  name: string
  createdAt: string | null
  status: CaseState
  pdfName: string
  rosterName: string | null
  cccdName: string | null
  cccdSummary: CccdSummary | null
  summary: CaseResultSummary | null
  error: string | null
  packets: PacketMeta[]
  progress: CaseProgress
  liveProgress?: Progress // present while status === 'processing'
}

// Vietnamese labels for the live progress banner, mirroring the Python report wording.
const STAGE_LABELS: Record<string, string> = {
  queued: 'Đang chờ…',
  splitting: 'Tách trang & phát hiện bìa, đối chiếu bảng kê…',
  ocr: 'Đọc dữ liệu từng hồ sơ (OCR)…',
  cccd: 'Đọc và ghép ảnh CCCD…',
  done: 'Hoàn tất',
  error: 'Lỗi',
}

export function stageLabel(stage: Stage): string {
  return STAGE_LABELS[stage] ?? stage
}

// Percent complete, clamped to [0,100]; 100 once stage is 'done' even if total is 0
// (e.g. a roster-less run with no packets), 0 while total is unknown otherwise.
export function progressPct(p: Progress): number {
  if (p.total) return Math.round(Math.min(1, p.done / p.total) * 100)
  return p.stage === 'done' ? 100 : 0
}

// Deep-map every docs[].pages[].src, prepending `base` to server-relative paths
// (the backend returns "/api/jobs/..." paths; the app runs on a different origin).
export function withAbsolutePageSrc(manifest: CtvFolder, base: string): CtvFolder {
  return {
    ...manifest,
    docs: manifest.docs.map(doc => ({
      ...doc,
      pages: doc.pages.map(page => ({
        ...page,
        src: page.src.startsWith('/') ? base + page.src : page.src,
      })),
    })),
  }
}

export async function listCases(): Promise<CaseSummary[]> {
  const res = await fetch(`${API_BASE}/api/cases`)
  if (!res.ok) throw new Error(`listCases: HTTP ${res.status}`)
  return res.json()
}

export async function getCase(caseId: string): Promise<CaseDetail> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}`)
  if (!res.ok) throw new Error(`getCase: HTTP ${res.status}`)
  const detail = await res.json() as CaseDetail
  return {
    ...detail,
    packets: detail.packets.map(normalizePacketMeta),
  }
}

export async function createCase(
  pdf: File,
  roster?: File,
  cccd?: File,
): Promise<{ case_id: string }> {
  const form = new FormData()
  form.append('pdf', pdf)
  if (roster) form.append('roster', roster)
  if (cccd) form.append('cccd', cccd)
  const res = await fetch(`${API_BASE}/api/cases`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`createCase: HTTP ${res.status}`)
  return res.json()
}

export async function setReview(
  caseId: string,
  index: number,
  review: PacketReview,
): Promise<{ packet: PacketMeta; progress: CaseProgress; status: CaseState }> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/packets/${index}/review`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(review),
  })
  if (!res.ok) throw new Error(`setReview: HTTP ${res.status}`)
  const result = await res.json() as {
    packet: PacketMeta
    progress: CaseProgress
    status: CaseState
  }
  return {
    ...result,
    packet: normalizePacketMeta(result.packet),
  }
}

function normalizePacketMeta(packet: PacketMeta): PacketMeta {
  return {
    ...packet,
    reviewFieldCount: Number.isFinite(packet.reviewFieldCount)
      ? Math.max(0, Math.trunc(packet.reviewFieldCount))
      : 0,
    review: normalizePacketReview(packet.review),
  }
}

export function normalizePacketReview(
  review: Partial<PacketReview> | null | undefined,
): PacketReview {
  return {
    done: Boolean(review?.done),
    fields: review?.fields ?? {},
    rejection: review?.rejection ?? null,
  }
}

export interface ReportItem {
  fieldKey: string
  fieldLabel: string
  document: string
  page: number | null
  rosterValue: string
  docValue: string
  reason: string
  note: string
}

export interface PacketRejectionReportEntry {
  reasons: PacketRejectionReason[]
  reasonLabels: string[]
  note: string
}

export interface ReportGroup {
  index: number
  name: string
  cccd: string
  matchedBy: MatchedBy
  identityIssue: boolean
  packetRejection: PacketRejectionReportEntry | null
  items: ReportItem[]
}

export interface Report {
  groups: ReportGroup[]
  markdown: string
  csv: string
}

export async function generateReport(caseId: string): Promise<Report> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/report`, { method: 'POST' })
  if (!res.ok) throw new Error(`generateReport: HTTP ${res.status}`)
  return res.json()
}

export function reportUrls(caseId: string) {
  return {
    md: `${API_BASE}/api/cases/${caseId}/report.md`,
    csv: `${API_BASE}/api/cases/${caseId}/report.csv`,
  }
}

/**
 * Whether a *person* decided this packet has something to send back.
 *
 * Mirrors `server/cases.py`'s `needs_resubmit`. A weak roster match is no longer
 * counted: that is something the machine noticed, and the engine's findings are
 * reported separately as candidates (`progress.candidates`, `findingCount`).
 * Prefer the server's `progress.flagged` where it is available — this exists for
 * per-packet rendering, and the two must not drift.
 */
export function packetNeedsResubmit(p: PacketMeta): boolean {
  if (p.review?.rejection) return true
  if (Object.values(p.review?.fields ?? {}).some(f => f.flag)) return true
  return Object.values(p.review?.overrides ?? {}).some(history => {
    const standing = history[history.length - 1]
    return standing?.toStatus === 'no' || standing?.toStatus === 'missing'
  })
}

export async function deleteCase(caseId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`deleteCase: HTTP ${res.status}`)
}

export async function fetchPacketManifest(caseId: string, index: number): Promise<CtvFolder> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/packets/${index}/manifest.json`)
  if (!res.ok) throw new Error(`fetchPacketManifest: HTTP ${res.status}`)
  const json = (await res.json()) as CtvFolder
  return withAbsolutePageSrc(json, API_BASE)
}

// "12/32 đã xong" (+ " · 3 cần gửi lại" when there's at least one flagged packet).
export function caseProgressLabel(p: CaseProgress): string {
  const base = `${p.done}/${p.total} đã xong`
  return p.flagged > 0 ? `${base} · ${p.flagged} cần gửi lại` : base
}

// --- manual CCCD card assignment --------------------------------------------
// About half the cards in a real workbook never yield a readable number, so the
// matcher can never place them. The reviewer places those by eye. The server
// returns ids and image URLs for UNATTACHED cards only — no file paths, no
// roster values.

export interface CccdCardSide {
  side: 'front' | 'back' | 'unknown'
  width: number
  height: number
}

export interface CccdCard {
  cardId: string
  state: string
  /** Which packet holds this card, or null when nothing has claimed it. */
  attachedPacketIndex: number | null
  /** What OCR read off the card — usually empty; that's why it's here. */
  number: string
  issues: string[]
  sides: CccdCardSide[]
}

export function cccdCardImageUrl(
  caseId: string,
  cardId: string,
  side: string,
): string {
  return `${API_BASE}/api/cases/${caseId}/cccd-cards/${encodeURIComponent(cardId)}/image/${side}`
}

/** Every card in the workbook — filter on `attachedPacketIndex`. */
export async function listCccdCards(caseId: string): Promise<CccdCard[]> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/cccd-cards`)
  if (!res.ok) throw new Error(`listCccdCards: HTTP ${res.status}`)
  const result = await res.json() as { cards: CccdCard[] }
  return result.cards
}

/** Attach `cardId` to a packet, or pass null to detach it. */
export async function assignCccdCard(
  caseId: string,
  cardId: string,
  packetIndex: number | null,
): Promise<{ cards: CccdCard[]; cccdSummary: CccdSummary | null }> {
  const res = await fetch(
    `${API_BASE}/api/cases/${caseId}/cccd-cards/${encodeURIComponent(cardId)}`,
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ packetIndex }),
    },
  )
  if (!res.ok) {
    const code = await res.json()
      .then(body => body?.detail?.code as string | undefined)
      .catch(() => undefined)
    throw new Error(code ?? `assignCccdCard: HTTP ${res.status}`)
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Tổng hợp tab — the five criteria Acc's checklist marks `Toàn bảng kê`
// (mirrors server/summary_criteria.py's payload 1:1).
// ---------------------------------------------------------------------------

export type SummaryStatus = 'ok' | 'no' | 'rv' | 'na' | 'missing' | 'pending'

export interface SummaryCriterion {
  stt: number
  code: string
  label: string
  group: string
  kind: string
  /** Documents this criterion reconciles across. */
  docs: string[]
  /** Acc's own instruction, so an abstention is never a dead end. */
  how: string
  status: SummaryStatus
  message: string
  /** Rows, packets or documents to look at, in Acc's phrasing. */
  detail: string[]
}

export interface SummaryPayload {
  criteria: SummaryCriterion[]
  counts: Record<SummaryStatus, number>
  /** CTV rows read off the bảng kê. */
  people: number
  /** Inputs the backend could not reach, e.g. `purchaseTotal`. */
  missing: string[]
  rosterName: string | null
}

export async function fetchCaseSummary(caseId: string): Promise<SummaryPayload> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/summary`)
  if (!res.ok) throw new Error(`fetchCaseSummary: HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Acc's 25-criterion matrix for one packet (mirrors server/evaluate.py's
// payload 1:1).
// ---------------------------------------------------------------------------

export interface CriterionEvidence {
  documentId: string
  page: number
  bbox: Bbox | null
  value: string
  confidence: number | null
  /** "ocr" | "idp" | "roster" | "override" — how strong a claim this is. */
  provenance: string
}

export interface CriterionCell {
  document: string
  status: SummaryStatus
  /** What the engine computed. Differs from `status` when a reviewer decided. */
  computedStatus?: SummaryStatus
  /** What was read here, verbatim. */
  value: string
  note: string
  /** Why a `pending` cell is pending. Absent on every other status.
   *
   *  One chip used to mean five different things, and only `unread` is about
   *  the packet in front of the reviewer -- measured over 166 real packets,
   *  `not-automated` is 41% of pending cells and `roster-level` 14%, and the
   *  latter is not unchecked at all: it is checked on the Tổng hợp tab. */
  pendingReason?:
    | 'not-automated'
    | 'roster-level'
    | 'no-roster-value'
    | 'unread'
    | 'unmatched'
    | null
  evidence: CriterionEvidence[]
}

/** One reviewer decision, as the server records it. */
export interface CriterionDecision {
  stt: number
  document: string
  fromStatus: SummaryStatus
  toStatus: SummaryStatus
  reason: string
  at: string
  /** Empty until there is auth to fill it. */
  by: string
}

export interface CriterionRow {
  stt: number
  code: string
  label: string
  group: string
  groupLabel: string
  kind: string
  render: 'matrix' | 'card'
  /** Acc's own instruction, for when the tool abstains. */
  how: string
  status: SummaryStatus
  note: string
  cells: CriterionCell[]
}

export interface CriteriaPayload {
  packet: number
  name: string
  /** Matrix column order; the Excel reference comes first. */
  documents: string[]
  criteria: CriterionRow[]
  counts: Record<SummaryStatus, number>
  groups: Record<string, { label: string; counts: Record<SummaryStatus, number> }>
  matchedRoster: boolean
}

export async function fetchPacketCriteria(
  caseId: string,
  index: number,
): Promise<CriteriaPayload> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/packets/${index}/criteria`)
  if (!res.ok) throw new Error(`fetchPacketCriteria: HTTP ${res.status}`)
  return res.json()
}

/**
 * Record a reviewer's decision on one criteria cell.
 *
 * One click: no reason and no confirmation, per Acc. `reason` stays available
 * for a reviewer who wants to record why.
 */
export async function decideCriterionCell(
  caseId: string,
  index: number,
  stt: number,
  document: string,
  toStatus: SummaryStatus,
  reason = '',
): Promise<{
  override: CriterionDecision
  history: CriterionDecision[]
  packet: PacketMeta
  status: CaseState
}> {
  const key = `${String(stt).padStart(2, '0')}:${document}`
  const res = await fetch(
    `${API_BASE}/api/cases/${caseId}/packets/${index}/criteria/${encodeURIComponent(key)}`,
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ toStatus, reason }),
    },
  )
  if (!res.ok) throw new Error(`decideCriterionCell: HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Upload pre-flight: what the backend inferred from these workbooks, declared
// before a ~50-minute run commits to it (docs/ver3-scope.md §1). Inference that
// is wrong and silent is the failure this exists to prevent.
// ---------------------------------------------------------------------------

export type ImageColumnKind = 'card' | 'bank' | 'tax' | null

export interface InspectedImageColumn {
  sheet: string
  column: string
  kind: ImageColumnKind
  count: number
}

export interface UploadInspection {
  /** The sheet chosen as the bảng kê, by content rather than by which tab was
   *  saved open. Null when no sheet qualified. */
  rosterSheet: string | null
  people: number
  columns: string[]
  images: InspectedImageColumn[]
}

export class RosterRejected extends Error {
  constructor(readonly reason: string) {
    super(reason)
    this.name = 'RosterRejected'
  }
}

export async function inspectUpload(
  roster: File,
  cccd?: File,
): Promise<UploadInspection> {
  const form = new FormData()
  form.append('roster', roster)
  if (cccd) form.append('cccd', cccd)
  const res = await fetch(`${API_BASE}/api/uploads/inspect`, {
    method: 'POST',
    body: form,
  })
  if (res.status === 422) {
    const body = await res.json().catch(() => null)
    throw new RosterRejected(body?.detail?.reason ?? 'invalid-roster-workbook')
  }
  if (!res.ok) throw new Error(`inspectUpload: HTTP ${res.status}`)
  return res.json()
}
