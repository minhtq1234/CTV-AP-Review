import type { PacketBoundaryAssessment } from '../upload/api'

export default function PacketBoundaryWarning({
  assessment,
}: {
  assessment: PacketBoundaryAssessment | undefined
}) {
  if (assessment?.status !== 'review') return null
  return (
    <div className="packet-boundary-warning" role="alert">
      <strong>Nghi ngờ nhiều hồ sơ trong một gói</strong>
      <span>
        AI phát hiện ranh giới hoặc danh tính không nhất quán. Hãy kiểm tra và
        xác nhận ranh giới trước khi kết luận hồ sơ.
      </span>
    </div>
  )
}
