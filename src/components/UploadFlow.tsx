import { useEffect, useRef, useState } from 'react'
import type { CtvFolder } from '../ctv/types'
import {
  listCases,
  getCase,
  createCase,
  setReview,
  deleteCase,
  fetchPacketManifest,
  normalizePacketReview,
} from '../upload/api'
import type { CaseSummary, CaseDetail as CaseDetailT, Progress, PacketReview } from '../upload/api'
import {
  createReviewSaveQueue,
  type ReviewSaveContext,
} from '../logic/reviewSaveQueue'
import { cccdReviewSeenKey, shouldOpenCccdReview } from '../logic/cccdReview'
import CaseList from './CaseList'
import UploadScreen from './UploadScreen'
import CaseDetail from './CaseDetail'
import CccdReviewScreen from './CccdReviewScreen'
import FolderReview from './FolderReview'
import ReportPanel from './ReportPanel'
import ReviewHeader from './ReviewHeader'

type Screen = 'list' | 'upload' | 'cccd' | 'detail' | 'review'

const CONN_ERR = 'Không kết nối được máy chủ xử lý (chạy backend ở cổng 8002).'

// localStorage throws outright in some locked-down browsers. The CCCD step's
// dismissal is a convenience, not data: on failure show the step once more
// rather than mistake a storage fault for a backend one.
function cccdReviewSeen(caseId: string): boolean {
  try {
    return window.localStorage.getItem(cccdReviewSeenKey(caseId)) !== null
  } catch {
    return false
  }
}

function markCccdReviewSeen(caseId: string): void {
  try {
    window.localStorage.setItem(cccdReviewSeenKey(caseId), new Date().toISOString())
  } catch {
    // Nothing else depends on this; the step simply shows again next time.
  }
}

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
  const [review, setReviewState] = useState<PacketReview>(
    normalizePacketReview(undefined),
  )
  const [err, setErr] = useState<string | null>(null)
  const [showReport, setShowReport] = useState(false)
  const activeReviewRef = useRef<{
    caseId: string | null
    packetIndex: number | null
  }>({ caseId: null, packetIndex: null })
  activeReviewRef.current = { caseId, packetIndex }
  const [reviewSaveQueue] = useState(() => createReviewSaveQueue(
    (context: ReviewSaveContext, candidate: PacketReview) => (
      setReview(context.caseId, context.packetIndex, candidate)
    ),
  ))

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
      setCaseId(id); setDetail(d)
      // Ver 3 step 1: confirm the CCCD mapping before the packet list. Shown
      // once per case per browser — a case with no workbook never sees it.
      const seen = cccdReviewSeen(id)
      setScreen(shouldOpenCccdReview(d.cccdSummary, seen) ? 'cccd' : 'detail')
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

  const onStart = async (pdf: File, roster?: File, cccd?: File) => {
    setErr(null); setBusy(true)
    try {
      const { case_id } = await createCase(pdf, roster, cccd)
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
      setReviewState(normalizePacketReview(meta?.review))
      setPacketIndex(index); setFolder(f); setScreen('review')
    } catch { setErr(CONN_ERR) }
  }

  const currentReviewContext = (): ReviewSaveContext | null => (
    caseId && packetIndex != null ? { caseId, packetIndex } : null
  )

  const applyReviewResult = (
    context: ReviewSaveContext,
    res: Awaited<ReturnType<typeof setReview>>,
    publishReview: boolean,
  ) => {
    setDetail(current => current?.id === context.caseId ? ({
      ...current,
      packets: current.packets.map(packet => (
        packet.index === context.packetIndex ? res.packet : packet
      )),
      status: res.status,
      progress: res.progress,
    }) : current)
    if (
      publishReview
      && activeReviewRef.current.caseId === context.caseId
      && activeReviewRef.current.packetIndex === context.packetIndex
    ) {
      setReviewState(res.packet.review)
    }
  }

  const saveOptimisticReview = (candidate: PacketReview) => {
    const context = currentReviewContext()
    if (!context) return
    setReviewState(candidate)
    void reviewSaveQueue.enqueue(context, candidate)
      .then(res => applyReviewResult(context, res, false))
      .catch(() => setErr(CONN_ERR))
  }

  const commitTransactionalReview = async (candidate: PacketReview) => {
    const context = currentReviewContext()
    if (!context) throw new Error('review packet is not active')
    const res = await reviewSaveQueue.enqueue(context, candidate)
    applyReviewResult(context, res, true)
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

  if (screen === 'cccd' && detail && caseId) {
    return (
      <CccdReviewScreen
        caseId={caseId}
        caseName={detail.name}
        packets={detail.packets}
        onContinue={() => {
          markCccdReviewSeen(caseId)
          setScreen('detail')
        }}
      />
    )
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
        <ReviewHeader
          name={folder.name}
          product={folder.product}
          pages={meta?.pages ?? [0, Math.max(0, folder.docs.reduce((sum, doc) => sum + doc.pages.length, 0) - 1)]}
          matchedBy={meta?.matchedBy ?? 'no-roster'}
          position={Math.max(0, pos)}
          count={packets.length}
          canPrevious={!!prev}
          canNext={!!next}
          onBack={() => setScreen('detail')}
          onPrevious={() => prev && onOpenPacket(prev.index)}
          onNext={() => next && onOpenPacket(next.index)}
        />
        <FolderReview
          key={packetIndex ?? folder.id}
          folder={folder}
          review={review}
          onReview={saveOptimisticReview}
          onCommitReview={commitTransactionalReview}
          caseId={caseId}
          packetIndex={packetIndex}
          onCardAssigned={() => {
            if (packetIndex != null) void onOpenPacket(packetIndex)
          }}
        />
      </div>
    )
  }

  return null
}
