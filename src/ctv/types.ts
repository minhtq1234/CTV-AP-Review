import type { Bbox, CaseStatus, FieldKind } from '../types'

// A CTV folder = one collaborator = one review case, backed by several evidence documents.
export type EvidenceKind = 'id_front' | 'id_back' | 'contract' | 'commitment'

export interface EvidenceDoc {
  id: string
  kind: EvidenceKind
  label: string
  src: string
  width: number   // natural px
  height: number  // natural px
}

export type CheckGroup = 'Danh tính' | 'Ngân hàng' | 'Thanh toán' | 'Chính sách'
export type CheckType = 'compare' | 'expiry' | 'math' | 'policy'

// What the AI "read" off one of the evidence documents (seeded, like the v1 predictions).
export interface CtvExtract {
  value: string
  docId: string   // which EvidenceDoc this was read from
  bbox: Bbox      // in that doc's natural px
  confidence: number
}

export interface CtvField {
  key: string
  label: string
  group: CheckGroup
  check: CheckType
  kind: FieldKind        // used when check === 'compare'
  expected: string       // the claimed value from the Excel row (source of truth for the request)
  extract: CtvExtract | null
}

export interface CtvFolder {
  id: string
  name: string
  product: string
  status: CaseStatus
  exempt: boolean        // PIT exemption claimed via bản cam kết
  docs: EvidenceDoc[]
  fields: CtvField[]
  rejectReason?: string
}
