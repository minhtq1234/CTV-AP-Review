// Client for the isolated v1 backend. Port 8002 keeps its field-keyed case data
// separate from the v2 checklist backend on port 8000.
// upload a scanned PDF (+ optional roster) as a durable **case**, list/inspect
// cases, fetch a packet's manifest as a CtvFolder the existing reviewer already
// knows how to render, and persist per-packet duyệt/từ chối decisions.
import type { CtvFolder } from '../ctv/types'

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

export type MatchedBy = 'cccd' | 'name' | 'unmatched' | 'no-roster'

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
}

export interface CaseProgress {
  done: number
  total: number
  flagged: number
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
}

// The pipeline's split/OCR summary — key names mirror server/pipeline.py's
// `run_pipeline` return value (snake_case, as produced by the real pipeline).
export interface CaseResultSummary {
  found: number
  roster_n: number | null
  matched: number
  auto_merged: number
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

export function packetNeedsResubmit(p: PacketMeta): boolean {
  const flagged = Object.values(p.review?.fields ?? {}).some(f => f.flag)
  return Boolean(p.review?.rejection)
    || flagged
    || p.matchedBy === 'name'
    || p.matchedBy === 'unmatched'
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
