// Client for the Stage B backend (server/app.py, http://127.0.0.1:8000): upload the
// scanned PDF (+ optional roster), poll job status, and fetch a packet's manifest as
// a CtvFolder the existing reviewer already knows how to render.
import type { CtvFolder } from '../ctv/types'

export const API_BASE = 'http://127.0.0.1:8000'

export type Stage = 'queued' | 'splitting' | 'ocr' | 'done' | 'error' | string

export interface Progress {
  stage: Stage
  done: number
  total: number
  detail: string
}

export interface PacketSummary {
  index: number
  name: string
  pages: [number, number]
  n_pages: number
  confidence: number
  flags: string[]
  labels: string[]
}

export interface JobResult {
  summary: {
    found: number
    roster_n: number | null
    matched: number
    auto_merged: number
  }
  packets: PacketSummary[]
}

export interface JobStatus {
  status: 'queued' | 'processing' | 'done' | 'error'
  progress: Progress
  result?: JobResult
  error?: string
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

export async function createJob(pdf: File, roster?: File): Promise<{ job_id: string }> {
  const form = new FormData()
  form.append('pdf', pdf)
  if (roster) form.append('roster', roster)
  const res = await fetch(`${API_BASE}/api/jobs`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`createJob: HTTP ${res.status}`)
  return res.json()
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`)
  if (!res.ok) throw new Error(`getJob: HTTP ${res.status}`)
  return res.json()
}

export async function fetchPacketManifest(jobId: string, index: number): Promise<CtvFolder> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/packets/${index}/manifest.json`)
  if (!res.ok) throw new Error(`fetchPacketManifest: HTTP ${res.status}`)
  const json = (await res.json()) as CtvFolder
  return withAbsolutePageSrc(json, API_BASE)
}
