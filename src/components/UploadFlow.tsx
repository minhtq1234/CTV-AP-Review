import { useEffect, useState } from 'react'
import type { CtvFolder } from '../ctv/types'
import { listCases, getCase, createCase, setDecision, deleteCase, fetchPacketManifest } from '../upload/api'
import type { CaseSummary, CaseDetail as CaseDetailT, Progress } from '../upload/api'
import CaseList from './CaseList'
import UploadScreen from './UploadScreen'
import ProcessingScreen from './ProcessingScreen'
import CaseDetail from './CaseDetail'
import FolderReview from './FolderReview'

type Screen = 'list' | 'upload' | 'processing' | 'detail' | 'review'

const CONN_ERR = 'Không kết nối được máy chủ xử lý (chạy backend ở cổng 8000).'
const DEFAULT_PROGRESS: Progress = { stage: 'queued', done: 0, total: 0, detail: '' }

// The "Tải hồ sơ" mode's screen router: case list (landing) → upload a new
// submission → watch real processing progress → case detail (packets, review
// progress) → open a packet into the existing FolderReview, whose duyệt/từ
// chối now persist to the backend (setDecision) instead of living only in
// local React state.
export default function UploadFlow() {
  const [screen, setScreen] = useState<Screen>('list')
  const [busy, setBusy] = useState(false)
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [caseId, setCaseId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CaseDetailT | null>(null)
  const [packetIndex, setPacketIndex] = useState<number | null>(null)
  const [folder, setFolder] = useState<CtvFolder | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const refreshList = async () => {
    try {
      setCases(await listCases())
    } catch {
      setErr(CONN_ERR)
    }
  }

  const backToList = () => {
    setScreen('list')
    setCaseId(null)
    setDetail(null)
    setPacketIndex(null)
    setFolder(null)
    refreshList()
  }

  const openCase = async (id: string) => {
    setErr(null)
    try {
      const d = await getCase(id)
      setCaseId(id)
      setDetail(d)
      setScreen(d.status === 'processing' ? 'processing' : 'detail')
    } catch {
      setErr(CONN_ERR)
    }
  }

  // Load the case list on mount and whenever we return to it.
  useEffect(() => {
    refreshList()
  }, [])

  // Resume a case via ?case=<id> — a case can take minutes to process (or sit
  // mid-review for days), so a refresh or a shared link can rejoin it directly
  // instead of hunting through the list.
  useEffect(() => {
    const cid = new URLSearchParams(window.location.search).get('case')
    if (cid) openCase(cid)
    // run once on mount only
    // eslint-disable-next-line
  }, [])

  const onNew = () => {
    setErr(null)
    setScreen('upload')
  }

  const onStart = async (pdf: File, roster?: File) => {
    setErr(null)
    setBusy(true)
    try {
      const { case_id } = await createCase(pdf, roster)
      setCaseId(case_id)
      setDetail(null)
      setScreen('processing')
    } catch {
      setErr(CONN_ERR)
    } finally {
      setBusy(false)
    }
  }

  const onDeleteCase = async (id: string) => {
    try {
      await deleteCase(id)
      await refreshList()
    } catch {
      setErr(CONN_ERR)
    }
  }

  // Poll case status every 800ms while processing; stop once it leaves
  // "processing" (ready/in_review/done/error) or on unmount.
  useEffect(() => {
    if (screen !== 'processing' || !caseId) return
    let cancelled = false

    const tick = async () => {
      try {
        const d = await getCase(caseId)
        if (cancelled) return
        setDetail(d)
        if (d.status === 'error') setErr(d.error ?? 'Lỗi xử lý không rõ nguyên nhân.')
        else if (d.status !== 'processing') setScreen('detail')
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
  }, [screen, caseId])

  const onOpenPacket = async (index: number) => {
    if (!caseId) return
    try {
      const f = await fetchPacketManifest(caseId, index)
      setPacketIndex(index)
      setFolder(f)
      setScreen('review')
    } catch {
      setErr(CONN_ERR)
    }
  }

  // Persist a duyệt/từ chối decision, then either jump straight to the next
  // unreviewed packet (keeps a reviewer moving through the batch with one
  // click per packet) or, once every packet is decided, back to case detail.
  const onDecide = async (decision: 'approved' | 'rejected', rejectReason?: string) => {
    if (!caseId || packetIndex == null) return
    try {
      await setDecision(caseId, packetIndex, decision, rejectReason)
      const d = await getCase(caseId)
      setDetail(d)
      const pending = d.packets.filter(p => p.decision === 'pending')
      const next = pending.find(p => p.index > packetIndex) ?? pending[0]
      if (next) await onOpenPacket(next.index)
      else setScreen('detail')
    } catch {
      setErr(CONN_ERR)
    }
  }

  if (err) {
    return (
      <div className="upload-screen">
        <div className="upload-card">
          <p className="upload-error">{err}</p>
          <button className="btn" onClick={() => { setErr(null); backToList() }}>Thử lại</button>
        </div>
      </div>
    )
  }

  if (screen === 'list') {
    return <CaseList cases={cases} onOpen={openCase} onNew={onNew} onDelete={onDeleteCase} />
  }

  if (screen === 'upload') {
    return <UploadScreen onStart={onStart} busy={busy} />
  }

  if (screen === 'processing') {
    return <ProcessingScreen progress={detail?.liveProgress ?? DEFAULT_PROGRESS} />
  }

  if (screen === 'detail' && detail) {
    return <CaseDetail detail={detail} onOpenPacket={onOpenPacket} onBack={backToList} />
  }

  if (screen === 'review' && folder) {
    return (
      <div className="review-flow">
        <div className="review-back-bar">
          <button className="btn" onClick={() => setScreen('detail')}>← Quay lại hồ sơ</button>
        </div>
        <FolderReview
          key={packetIndex ?? folder.id}
          folder={folder}
          onUpdate={f => {
            setFolder(f)
            if (f.status === 'approved') onDecide('approved')
            else if (f.status === 'rejected') onDecide('rejected', f.rejectReason)
          }}
        />
      </div>
    )
  }

  return null
}
