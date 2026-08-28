// Turning the backend's pre-flight inspection into what the reviewer reads.
// docs/ver3-scope.md §1: the tool infers which sheet is the bảng kê and which
// columns hold which images, and inference "can be confidently wrong and
// silent". So it is declared, and confirmed, before a full run.
import type { InspectedImageColumn, UploadInspection } from '../upload/api'

const KIND_LABEL: Record<string, string> = {
  card: 'ảnh CCCD',
  bank: 'ảnh sao kê ngân hàng',
  tax: 'ảnh tra cứu thuế',
}

/** An image column whose header explained nothing. Named separately because
 *  this is the case the reviewer most needs to notice, not the least. */
export const UNRECOGNISED = 'ảnh chưa nhận dạng'

export function imageColumnLine(column: InspectedImageColumn): string {
  const label = column.kind ? KIND_LABEL[column.kind] : UNRECOGNISED
  return `${column.count} ${label} · cột ${column.column} (sheet ${column.sheet})`
}

export function rosterLine(inspection: UploadInspection): string {
  if (!inspection.rosterSheet) return 'Không nhận ra sheet bảng kê'
  return `Bảng kê đọc từ sheet “${inspection.rosterSheet}” · ${inspection.people} người`
}

/** Whether anything here needs a second look before committing to a run. */
export function needsAttention(inspection: UploadInspection): boolean {
  if (!inspection.rosterSheet) return true
  if (inspection.people === 0) return true
  return inspection.images.some(image => image.kind === null)
}
