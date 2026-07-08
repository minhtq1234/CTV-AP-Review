export type Verdict = 'match' | 'fuzzy' | 'mismatch' | 'low_conf'
export type FieldKind = 'number' | 'date' | 'text' | 'name'
export type CaseStatus = 'pending' | 'approved' | 'rejected'

export interface Bbox { x: number; y: number; width: number; height: number }

export interface Prediction {
  value: string
  page: number            // 0-based page index
  bbox: Bbox              // natural pixels
  confidence: number      // 0..1
}

export interface CaseField {
  key: string
  label: string           // Vietnamese label
  kind: FieldKind
  expected: string        // typed request-form value
  prediction: Prediction | null
}

export interface DocPage { src: string; width: number; height: number; label?: string }

export interface Case {
  id: string
  title: string
  requester: string
  category: string
  status: CaseStatus
  pages: DocPage[]
  fields: CaseField[]
}

export interface Frame { scale: number; tx: number; ty: number }
