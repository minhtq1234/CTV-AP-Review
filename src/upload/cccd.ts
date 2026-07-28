import type { CccdSummary } from './api'

export const CCCD_ROSTER_REQUIRED = 'Cần bảng kê để tự động ghép CCCD.'

export function formatCccdSummary(summary: CccdSummary): string {
  if (summary.status === 'error') {
    return 'CCCD: Không xử lý được file ảnh'
  }
  return `CCCD: ${summary.attached} đã gắn · ${summary.unresolved} chưa ghép`
}

export function cccdRequirementMessage(
  hasRoster: boolean,
  hasCccd: boolean,
): string | null {
  return hasCccd && !hasRoster ? CCCD_ROSTER_REQUIRED : null
}

export function canStartUpload(
  hasPdf: boolean,
  hasRoster: boolean,
  hasCccd: boolean,
  busy: boolean,
): boolean {
  return hasPdf
    && !busy
    && cccdRequirementMessage(hasRoster, hasCccd) === null
}
