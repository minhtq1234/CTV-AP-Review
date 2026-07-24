import { useEffect, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvFolder, DocRecap, EvidenceDoc } from '../ctv/types'
import type { PacketReview, FieldFlag, MatchedBy, Identity } from '../upload/api'
import { allSeen } from '../logic/review'
import { stepPage, stepDoc } from '../logic/pageNav'
import { viewModeForCheck, type ViewMode } from '../logic/viewMode'
import ChecklistPanel from './ChecklistPanel'
import EvidenceViewer from './EvidenceViewer'
import ActionBar from './ActionBar'
import MatchKeyStrip from './MatchKeyStrip'
import ReferenceLightbox from './ReferenceLightbox'

interface Props {
  folder: CtvFolder
  review: PacketReview
  matchedBy: MatchedBy
  ocrIdentity: Identity
  rosterIdentity: Identity | null
  onReview: (review: PacketReview) => void
  getRecap?: (doc: EvidenceDoc) => Promise<DocRecap>  // seam: forwarded to the doc pane
}

export default function FolderReview({ folder, review, matchedBy, ocrIdentity, rosterIdentity, onReview, getRecap }: Props) {
  const checks = folder.checks ?? []
  const [selectedCode, setSelectedCode] = useState(checks[0]?.code ?? '')
  const [activeDocId, setActiveDocId] = useState(checks[0]?.evidenceDocId ?? folder.docs[0].id)
  const [activePage, setActivePage] = useState(checks[0]?.source?.page ?? 0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(checks[0]?.source?.bbox ?? null)
  const [lockView, setLockView] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>(checks[0] ? viewModeForCheck(checks[0]) : 'cont')
  const [refAsset, setRefAsset] = useState<{ src: string; title: string } | null>(null)

  // Mark a check as seen the first time it's focused — a no-op (no onReview call) if it's
  // already seen, so re-focusing / the mount-seed effect below never loops.
  const markSeen = (code: string) => {
    if (review.items[code]?.seen) return
    onReview({
      ...review,
      items: { ...review.items, [code]: { seen: true, flag: review.items[code]?.flag ?? null } },
    })
  }

  const toggleFlag = (code: string, flag: FieldFlag | null) => {
    onReview({ ...review, items: { ...review.items, [code]: { seen: true, flag } } })
  }

  // Focus a checklist row (#2): switch the scan pane to this check's evidence document. A VALUE
  // check auto-focuses its located field (single page, zoom + red box + pinned bảng-kê value);
  // signature/glance/confirm checks just open the doc (continuous scroll), no auto-focus. A manual
  // toolbar toggle (cont/2) holds while the reviewer stays on the same check.
  const focusCheck = (code: string) => {
    const isNewCheck = code !== selectedCode
    setSelectedCode(code)
    const c = checks.find(x => x.code === code)
    if (!c) return
    setActiveDocId(c.evidenceDocId ?? folder.docs[0]?.id ?? '')
    if (isNewCheck) setViewMode(viewModeForCheck(c))
    if (c.kind === 'value' && c.source) {
      setActivePage(c.source.page); setFocusBbox(c.source.bbox)
    } else {
      setActivePage(0); setFocusBbox(null)
    }
    markSeen(code)
  }

  // Open the first check on mount exactly as focusing it would — switch to its doc + mark seen.
  useEffect(() => { if (checks[0]) focusCheck(checks[0].code) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Hotkeys — input-focus + alt/ctrl/meta guards so browser/OS shortcuts (e.g. ⌘F find) pass
  // through untouched. `F` flags the selected check; ↑↓ walk the checklist order; ←→ step
  // through pages of the active document, rolling into the adjacent doc at the first/last page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (refAsset) return   // reference lightbox open — don't flag/navigate the hidden checklist
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        const cur = review.items[selectedCode]?.flag
        toggleFlag(selectedCode, cur ? null : { reason: '', note: '' })
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const i = checks.findIndex(c => c.code === selectedCode)
        const next = e.key === 'ArrowDown' ? Math.min(i + 1, checks.length - 1) : Math.max(i - 1, 0)
        focusCheck(checks[next].code)
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault()
        const dir = e.key === 'ArrowRight' ? 1 : -1
        if (viewMode === 'cont') {
          // Continuous scroll already walks pages by wheel/trackpad, so ←→ jumps documents.
          const docId = stepDoc(folder.docs, activeDocId, dir)
          if (docId !== activeDocId) { setActiveDocId(docId); setActivePage(0); setFocusBbox(null) }
        } else {
          const next = stepPage(folder.docs, activeDocId, activePage, dir)
          if (next.docId !== activeDocId || next.page !== activePage) {
            setActiveDocId(next.docId)
            setActivePage(next.page)
            setFocusBbox(null)   // paging away from a located field clears its box
          }
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [checks, selectedCode, review, folder, activeDocId, activePage, viewMode, refAsset])

  const sel = checks.find(c => c.code === selectedCode)
  const codes = checks.map(c => c.code)
  const seenCount = codes.filter(k => review.items[k]?.seen).length

  return (
    <div className="screen">
      <header className="screen-head">
        <div><strong>{folder.heading ?? 'Hồ sơ CTV'} · {folder.name}</strong> — {folder.product}</div>
        <MatchKeyStrip matchedBy={matchedBy} ocr={ocrIdentity} roster={rosterIdentity} />
      </header>
      <div className="panes">
        <ChecklistPanel checks={checks} review={review} selectedCode={selectedCode}
          onSelect={focusCheck} onToggleFlag={toggleFlag}
          onOpenReference={(src, label) => setRefAsset({ src, title: `Mẫu chuẩn — ${label}` })} />
        <EvidenceViewer docs={folder.docs} activeDocId={activeDocId} activePage={activePage}
          focusBbox={focusBbox} lockView={lockView}
          viewMode={viewMode} onSetViewMode={setViewMode} getRecap={getRecap}
          onSelectDoc={id => { setActiveDocId(id); setActivePage(0); setFocusBbox(null) }}
          onSelectPage={p => { setActivePage(p); setFocusBbox(null) }}
          onToggleLock={() => setLockView(v => !v)}
          rosterLabel={sel?.label}
          rosterValue={sel?.kind === 'value' ? sel.reference : null}
          disabled={!!refAsset} />
        <ReferenceLightbox src={refAsset?.src ?? null} title={refAsset?.title ?? ''} onClose={() => setRefAsset(null)} />
      </div>
      <ActionBar done={review.done} seenCount={seenCount} total={codes.length}
        hint="↑↓ mục · ←→ trang · F đánh dấu · B khung · V bảng kê · ⌥P di chuyển · ? phím tắt"
        onFinish={() => { if (codes.length > 0 && allSeen(review, codes)) onReview({ ...review, done: true }) }} />
    </div>
  )
}
