import { useEffect, useState } from 'react'
import type { CtvFolder } from '../ctv/types'
import { listCases, getCase, createCase, setReview, deleteCase, fetchPacketManifest, fetchDocRecap } from '../upload/api'
import type { CaseSummary, CaseDetail as CaseDetailT, Progress, PacketReview } from '../upload/api'
import CaseList from './CaseList'
import UploadScreen from './UploadScreen'
import CaseDetail from './CaseDetail'
import FolderReview from './FolderReview'
import ReportPanel from './ReportPanel'

type Screen = 'list' | 'upload' | 'detail' | 'review'

const CONN_ERR = 'Không kết nối được máy chủ xử lý (chạy backend ở cổng 8000).'

// The "Tải hồ sơ" flow. After an upload we return straight to the case list —
// processing happens in the background and shows as an inline progress bar on the
// case's own row (no blocking full-screen spinner). Opening a case → case detail
// → a packet → the existing FolderReview, whose per-field review state persists (setReview).
export default function UploadFlow() {
  const [screen, setScreen] = useState<Screen>('list')
  const [busy, setBusy] = useState(false)
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [live, setLive] = useState<Record<string, Progress>>({})
  const [caseId, setCaseId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CaseDetailT | null>(null)
  const [packetIndex, setPacketIndex] = useState<number | null>(null)
  const [folder, setFolder] = useState<CtvFolder | null>(null)
  const [review, setReviewState] = useState<PacketReview>({ done: false, items: {} })
  const [err, setErr] = useState<string | null>(null)
  const [showReport, setShowReport] = useState(false)

  const refreshList = async () => {
    try { setCases(await listCases()) } catch { setErr(CONN_ERR) }
  }

  const backToList = () => {
    setScreen('list'); setCaseId(null); setDetail(null)
    setPacketIndex(null); setFolder(null); refreshList()
  }

  const openCase = async (id: string) => {
    setErr(null)
    try {
      const d = await getCase(id)
      // A still-processing case has nothing to review yet — keep it on the list,
      // where its row shows live progress.
      if (d.status === 'processing') { setScreen('list'); refreshList(); return }
      setCaseId(id); setDetail(d); setScreen('detail')
    } catch { setErr(CONN_ERR) }
  }

  // Load the list on mount.
  useEffect(() => { refreshList() }, [])

  // Resume a case via ?case=<id> (a shared link or a refresh mid-review).
  useEffect(() => {
    const cid = new URLSearchParams(window.location.search).get('case')
    if (cid) openCase(cid)
    // run once on mount only
    // eslint-disable-next-line
  }, [])

  // While the list is showing, poll it; for any case still processing, pull its
  // live OCR progress for the inline row bar. The interval stops once nothing is
  // processing, and is re-armed whenever we (re-)enter the list (e.g. after an
  // upload, which transitions upload → list).
  useEffect(() => {
    if (screen !== 'list') return
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | null = null
    const poll = async () => {
      try {
        const list = await listCases()
        if (cancelled) return
        setCases(list)
        const proc = list.filter(c => c.status === 'processing')
        if (proc.length) {
          const entries = await Promise.all(proc.map(async c => {
            try { return [c.id, (await getCase(c.id)).liveProgress] as const }
            catch { return [c.id, undefined] as const }
          }))
          if (cancelled) return
          setLive(prev => {
            const next = { ...prev }
            for (const [id, lp] of entries) if (lp) next[id] = lp
            return next
          })
        } else if (timer) { clearInterval(timer); timer = null }
      } catch { /* transient poll error — ignore, next tick retries */ }
    }
    poll()
    timer = setInterval(poll, 1500)
    return () => { cancelled = true; if (timer) clearInterval(timer) }
  }, [screen])

  const onNew = () => { setErr(null); setScreen('upload') }

  const onStart = async (pdf: File, roster?: File) => {
    setErr(null); setBusy(true)
    try {
      const { case_id } = await createCase(pdf, roster)
      setCaseId(case_id)
      setScreen('list')     // straight back to the list; the new case processes inline
      refreshList()
    } catch { setErr(CONN_ERR) } finally { setBusy(false) }
  }

  const onDeleteCase = async (id: string) => {
    try { await deleteCase(id); await refreshList() } catch { setErr(CONN_ERR) }
  }

  const onOpenPacket = async (index: number) => {
    if (!caseId) return
    try {
      const f = await fetchPacketManifest(caseId, index)
      const meta = detail?.packets.find(p => p.index === index)
      setReviewState(meta?.review ?? { done: false, items: {} })
      setPacketIndex(index); setFolder(f); setScreen('review')
    } catch { setErr(CONN_ERR) }
  }

  // Persist review changes (seen fields, flags, done) as the reviewer works
  // through a packet, and keep case detail (grid + prev/next + progress) in sync.
  const flushReview = async (r: PacketReview) => {
    if (!caseId || packetIndex == null) return
    try {
      const res = await setReview(caseId, packetIndex, r)
      setDetail(d => d && ({
        ...d,
        packets: d.packets.map(p => p.index === packetIndex ? res.packet : p),
        status: res.status,
        progress: res.progress,
      }))
    } catch { setErr(CONN_ERR) }
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
    return <CaseList cases={cases} live={live} onOpen={openCase} onNew={onNew} onDelete={onDeleteCase} />
  }

  if (screen === 'upload') {
    return <UploadScreen onStart={onStart} busy={busy} />
  }

  if (screen === 'detail' && detail) {
    return (
      <>
        <CaseDetail detail={detail} onOpenPacket={onOpenPacket} onBack={backToList}
          onExport={() => setShowReport(true)} />
        {showReport && caseId && <ReportPanel caseId={caseId} onClose={() => setShowReport(false)} />}
      </>
    )
  }

  if (screen === 'review' && folder) {
    // Prev/next scrub across the whole submission, by list order.
    const packets = detail?.packets ?? []
    const pos = packets.findIndex(p => p.index === packetIndex)
    const prev = pos > 0 ? packets[pos - 1] : null
    const next = pos >= 0 && pos < packets.length - 1 ? packets[pos + 1] : null
    const meta = detail?.packets.find(p => p.index === packetIndex)
    return (
      <div className="review-flow">
        <div className="review-back-bar">
          <button className="btn" onClick={() => setScreen('detail')}>← Quay lại hồ sơ</button>
          <div className="review-nav">
            <button
              className="btn"
              disabled={!prev}
              title={prev ? `Gói trước: ${prev.name || 'chưa khớp tên'}` : undefined}
              onClick={() => prev && onOpenPacket(prev.index)}
            >
              ← Gói trước
            </button>
            <span className="review-nav-pos">{pos >= 0 ? `Gói ${pos + 1} / ${packets.length}` : ''}</span>
            <button
              className="btn"
              disabled={!next}
              title={next ? `Gói sau: ${next.name || 'chưa khớp tên'}` : undefined}
              onClick={() => next && onOpenPacket(next.index)}
            >
              Gói sau →
            </button>
          </div>
        </div>
        <FolderReview
          key={packetIndex ?? folder.id}
          folder={folder}
          review={review}
          matchedBy={meta?.matchedBy ?? 'no-roster'}
          ocrIdentity={meta?.ocrIdentity ?? { cccd: '', name: '' }}
          rosterIdentity={meta?.rosterIdentity ?? null}
          getRecap={caseId && packetIndex != null
            ? doc => fetchDocRecap(caseId, packetIndex, doc.id)
            : undefined}
          onReview={r => { setReviewState(r); flushReview(r) }}
        />
      </div>
    )
  }

  return null
}
