import {
  PACKET_REJECTION_REASONS,
  type PacketRejection,
  type PacketRejectionReason,
  type PacketReview,
} from '../upload/api'
import { allSeen } from './review'

export const PACKET_REJECTION_OPTIONS: ReadonlyArray<{
  value: PacketRejectionReason
  label: string
}> = [
  { value: 'missing_documents', label: 'Thiếu chứng từ' },
  { value: 'wrong_template', label: 'Chứng từ không đúng mẫu' },
  { value: 'missing_signature', label: 'Thiếu chữ ký' },
]

export function normalizeRejectionDraft(
  reasons: PacketRejectionReason[],
  note: string,
): PacketRejection {
  const selected = new Set(reasons)
  const normalized = PACKET_REJECTION_REASONS.filter(reason => selected.has(reason))
  if (normalized.length === 0) throw new Error('Chọn ít nhất một lý do')
  return { reasons: normalized, note: note.trim() }
}

export function rejectedReview(
  review: PacketReview,
  rejection: PacketRejection,
): PacketReview {
  return {
    ...review,
    done: true,
    fields: review.fields,
    rejection,
  }
}

export function undoRejectedReview(
  review: PacketReview,
  fieldKeys: string[],
): PacketReview {
  return {
    ...review,
    done: allSeen(review, fieldKeys),
    fields: review.fields,
    rejection: null,
  }
}
