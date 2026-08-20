import type { CtvFolder } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import type { PacketBoundaryAssessment } from '../upload/api'

export type PacketAiResult = 'match' | 'review' | 'mismatch'

export interface PacketEvidenceSummary {
  taxCommitmentDetected: boolean
  documents: {
    present: number
    total: number
    missing: string[]
  }
  aiResult: PacketAiResult
}

export function summarizePacketEvidence(
  folder: CtvFolder,
  boundaryAssessment?: PacketBoundaryAssessment,
): PacketEvidenceSummary {
  const kinds = new Set(folder.docs.map(doc => doc.kind))
  const taxCommitmentDetected = kinds.has('commitment')
  const required = [
    { label: 'CCCD', present: kinds.has('id_front') && kinds.has('id_back') },
    { label: 'Hợp đồng', present: kinds.has('contract') },
    { label: 'BBNT', present: kinds.has('bbnt') },
    { label: 'Bảng kê', present: kinds.has('appendix') },
  ]
  if (taxCommitmentDetected) {
    required.push({ label: 'Cam kết thuế', present: true })
  }
  const missing = required
    .filter(document => !document.present)
    .map(document => document.label)
  const verdicts = rankFolder(folder).map(result => result.verdict)
  const aiResult: PacketAiResult = boundaryAssessment?.status === 'review'
    ? 'review'
    : missing.length > 0 || verdicts.includes('mismatch')
      ? 'mismatch'
      : verdicts.some(verdict => (
        verdict === 'review' || verdict === 'low_conf' || verdict === 'fuzzy'
      ))
        ? 'review'
        : 'match'

  return {
    taxCommitmentDetected,
    documents: {
      present: required.length - missing.length,
      total: required.length,
      missing,
    },
    aiResult,
  }
}
