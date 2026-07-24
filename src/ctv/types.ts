import type { Bbox, CaseStatus, FieldKind } from '../types'

// A CTV folder = one collaborator = one review case, backed by several evidence documents,
// each of which can span multiple pages.
// 'appendix' (#010): an SOW/KPI evaluation appendix (Phụ lục) -- its own kind, distinct
// from 'pit' (Tra cứu thuế), which it used to share a kind with before #010.
export type EvidenceKind = 'id_front' | 'id_back' | 'contract' | 'commitment' | 'pit' | 'bbnt' | 'appendix'

// AI recap of a content-bearing doc (Tóm tắt + Nhận định + footer disclaimer). An
// assist, never a verdict — displaying it never marks or flags a check.
export interface DocRecap {
  bullets: string[]   // Tóm tắt — 2–3 plain bullets
  nhanDinh: string    // Nhận định — a tentative conclusion
  disclaimer: string  // footer disclaimer
}

export interface DocPage { src: string; width: number; height: number } // natural px

export interface EvidenceDoc {
  id: string
  kind: EvidenceKind
  label: string
  pages: DocPage[]
  recap?: DocRecap   // canned recap baked into synthetic demo packets (offline export)
}

export type CheckGroup = 'Danh tính' | 'Ngân hàng' | 'Thanh toán' | 'Chính sách' | 'Chứng từ' | 'Chuyến đi'
export type CheckType = 'compare' | 'expiry' | 'math' | 'policy'

// One place a field's value was found — a specific page of a specific document.
export interface CtvSource {
  docId: string
  page: number      // 0-based page index within the doc
  value: string     // what the AI read here
  bbox: Bbox        // in that page's natural px
  confidence: number
}

export type CheckTier = 'gate' | 'detail'
export type CheckKind = 'value' | 'identity' | 'confirm'
export type CheckAutoStatus = 'match' | 'mismatch' | 'review'

// One row of the reviewer checklist. Built by the backend (server/checklist.py) from
// the packet's OCR fields + match key + segmented docs, and carried in the manifest
// under `checks`. `source` is a located value on a scanned doc (value kind only).
export interface CheckItem {
  code: string
  label: string
  tier: CheckTier
  kind: CheckKind
  evidenceDocId: string | null
  reference: string | null
  source: CtvSource | null
  autostatus: CheckAutoStatus | null
}

export interface CtvField {
  key: string
  label: string
  group: CheckGroup
  check: CheckType
  kind: FieldKind          // used when check === 'compare'
  expected: string         // the claimed value from the Excel row (the reference)
  sources: CtvSource[]     // every document/page this value appears in — cross-checked against `expected`
}

export interface CtvFolder {
  id: string
  name: string
  product: string
  heading?: string         // panel header label (defaults to "Hồ sơ CTV")
  status: CaseStatus
  exempt: boolean          // PIT exemption claimed via bản cam kết (n/a for flight cases)
  docs: EvidenceDoc[]
  fields: CtvField[]
  checks?: CheckItem[]     // coded reviewer checklist rows (server/checklist.py); optional for now
  rejectReason?: string
}
