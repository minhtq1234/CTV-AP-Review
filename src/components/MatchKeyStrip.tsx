import type { MatchedBy, Identity } from '../upload/api'

interface Props {
  matchedBy: MatchedBy
  ocr?: Identity
  roster?: Identity | null
}

const BADGE: Record<MatchedBy, { label: string; cls: string }> = {
  cccd: { label: 'Khớp theo CCCD', cls: 'ok' },
  // A strong identifier, so it reads as reliable rather than as a caution.
  mst: { label: 'Khớp theo MST', cls: 'ok' },
  name: { label: 'Khớp theo họ tên', cls: 'warn' },
  unmatched: { label: 'Chưa khớp bảng kê', cls: 'bad' },
  'no-roster': { label: 'Không có bảng kê', cls: 'muted' },
}

export default function MatchKeyStrip({ matchedBy }: Props) {
  const badge = BADGE[matchedBy]
  return (
    <div className="matchkey">
      <span className={`match-badge ${badge.cls}`}>{badge.label}</span>
    </div>
  )
}
