import { useEffect, useState } from 'react'
import type { CtvFolder } from '../ctv/types'
import { createJob, getJob, fetchPacketManifest } from '../upload/api'
import type { JobStatus } from '../upload/api'
import UploadScreen from './UploadScreen'
import ProcessingScreen from './ProcessingScreen'
import SplitResultScreen from './SplitResultScreen'
import FolderReview from './FolderReview'

type Phase = 'upload' | 'processing' | 'result' | 'review'

const CONN_ERR = 'Không kết nối được máy chủ xử lý (chạy backend ở cổng 8000).'

// The "Tải hồ sơ" mode's phase state machine: upload the scan → watch real
// processing progress (polling the backend) → see the split result → open a
// packet into the existing FolderReview for real field validation.
export default function UploadFlow() {
  const [phase, setPhase] = useState<Phase>('upload')
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [packetIndex, setPacketIndex] = useState<number | null>(null)
  const [folder, setFolder] = useState<CtvFolder | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const reset = () => {
    setPhase('upload')
    setBusy(false)
    setJobId(null)
    setStatus(null)
    setPacketIndex(null)
    setFolder(null)
    setErr(null)
  }

  const onStart = async (pdf: File, roster?: File) => {
    setErr(null)
    setBusy(true)
    try {
      const { job_id } = await createJob(pdf, roster)
      setJobId(job_id)
      setPhase('processing')
    } catch {
      setErr(CONN_ERR)
    } finally {
      setBusy(false)
    }
  }

  // Poll job status every 800ms while processing; stop on done/error or unmount.
  useEffect(() => {
    if (phase !== 'processing' || !jobId) return
    let cancelled = false

    const tick = async () => {
      try {
        const s = await getJob(jobId)
        if (cancelled) return
        setStatus(s)
        if (s.status === 'done') setPhase('result')
        else if (s.status === 'error') setErr(s.error ?? 'Lỗi xử lý không rõ nguyên nhân.')
      } catch {
        if (!cancelled) setErr(CONN_ERR)
      }
    }

    tick()
    const id = setInterval(tick, 800)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [phase, jobId])

  const onOpen = async (index: number) => {
    if (!jobId) return
    try {
      const f = await fetchPacketManifest(jobId, index)
      setPacketIndex(index)
      setFolder(f)
      setPhase('review')
    } catch {
      setErr(CONN_ERR)
    }
  }

  if (err) {
    return (
      <div className="upload-screen">
        <div className="upload-card">
          <p className="upload-error">{err}</p>
          <button className="btn" onClick={reset}>Thử lại</button>
        </div>
      </div>
    )
  }

  if (phase === 'upload') return <UploadScreen onStart={onStart} busy={busy} />

  if (phase === 'processing') {
    return (
      <ProcessingScreen
        status={status ?? { status: 'queued', progress: { stage: 'queued', done: 0, total: 0, detail: '' } }}
      />
    )
  }

  if (phase === 'result' && status?.result) {
    return <SplitResultScreen result={status.result} onOpen={onOpen} onReset={reset} />
  }

  if (phase === 'review' && folder) {
    return (
      <div className="review-flow">
        <div className="review-back-bar">
          <button className="btn" onClick={() => setPhase('result')}>← Quay lại danh sách</button>
        </div>
        <FolderReview key={packetIndex ?? folder.id} folder={folder} onUpdate={setFolder} />
      </div>
    )
  }

  return null
}
