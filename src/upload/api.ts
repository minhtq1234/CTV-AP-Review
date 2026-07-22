// Client for the case-management backend (server/app.py, http://127.0.0.1:8000):
// upload a scanned PDF (+ optional roster) as a durable **case**, list/inspect
// cases, fetch a packet's manifest as a CtvFolder the existing reviewer already
// knows how to render, and persist per-packet duyệt/từ chối decisions.
import type { CtvFolder } from '../ctv/types'

export const API_BASE = 'http://127.0.0.1:8000'

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
export type Decision = 'pending' | 'approved' | 'rejected'

export interface CaseProgress {
  decided: number
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
  labels?: string[]
  decision: Decision
  rejectReason: string | null
  reviewedAt: string | null
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

export interface CaseDetail {
  id: string
  name: string
  createdAt: string | null
  status: CaseState
  pdfName: string
  rosterName: string | null
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
  return res.json()
}

export async function createCase(pdf: File, roster?: File): Promise<{ case_id: string }> {
  const form = new FormData()
  form.append('pdf', pdf)
  if (roster) form.append('roster', roster)
  const res = await fetch(`${API_BASE}/api/cases`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`createCase: HTTP ${res.status}`)
  return res.json()
}

export async function setDecision(
  caseId: string,
  index: number,
  decision: Decision,
  rejectReason?: string | null,
): Promise<{ packet: PacketMeta; progress: CaseProgress; status: CaseState }> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/packets/${index}/decision`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ decision, rejectReason: rejectReason ?? null }),
  })
  if (!res.ok) throw new Error(`setDecision: HTTP ${res.status}`)
  return res.json()
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

// "12/32 đã duyệt" (+ " · 3 cần xem" when there's at least one flagged/amber packet).
export function caseProgressLabel(p: CaseProgress): string {
  const base = `${p.decided}/${p.total} đã duyệt`
  return p.flagged > 0 ? `${base} · ${p.flagged} cần xem` : base
}

const DECISION_BADGE: Record<Decision, string> = {
  approved: '✓ Đã duyệt',
  rejected: '✗ Từ chối',
  pending: 'Chưa xem',
}

export function decisionBadge(d: Decision): string {
  return DECISION_BADGE[d]
}
