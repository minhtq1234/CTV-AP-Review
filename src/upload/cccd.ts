export const CCCD_ROSTER_REQUIRED = 'Cần bảng kê để tự động ghép CCCD.'

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
  return hasPdf && !busy && cccdRequirementMessage(hasRoster, hasCccd) === null
}
