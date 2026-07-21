import { progressPct, stageLabel } from '../upload/api'
import type { JobStatus } from '../upload/api'

interface Props { status: JobStatus }

// Live progress while the backend splits + OCRs the upload. Polled by UploadFlow
// every 800ms; this component is purely presentational over the latest JobStatus.
export default function ProcessingScreen({ status }: Props) {
  const { stage, done, total, detail } = status.progress
  const pct = progressPct(status.progress)
  const counts = total > 0 ? `gói ${done}/${total}` : ''
  const line = [counts, detail].filter(Boolean).join(' · ')

  return (
    <div className="upload-screen">
      <div className="upload-card processing-card">
        <div className="spinner" aria-hidden="true" />
        <h2>{stageLabel(stage)}</h2>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="progress-detail">{line || ' '}</div>
      </div>
    </div>
  )
}
