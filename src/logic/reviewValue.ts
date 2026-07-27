import type { CtvField } from '../ctv/types'

type ReviewValueField = Pick<CtvField, 'group' | 'kind' | 'expected'>

export function formatRosterValue(field: ReviewValueField): string {
  if (field.group !== 'Thanh toán' || field.kind !== 'number') {
    return field.expected
  }

  const amount = field.expected
    .trim()
    .replace(/\s*(?:₫|VND)\s*$/i, '')
    .replace(/[.,\s]/g, '')

  if (!/^\d+$/.test(amount)) return field.expected
  return `${BigInt(amount).toLocaleString('vi-VN')} ₫`
}
