import { useEffect, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvFolder } from '../ctv/types'
import type { PacketReview, FieldFlag, MatchedBy, Identity } from '../upload/api'
import { allSeen } from '../logic/review'
import ChecklistPanel from './ChecklistPanel'
import EvidenceViewer from './EvidenceViewer'
import ActionBar from './ActionBar'
import MatchKeyStrip from './MatchKeyStrip'

interface Props {
  folder: CtvFolder
  review: PacketReview
  matchedBy: MatchedBy
  ocrIdentity: Identity
  rosterIdentity: Identity | null
  onReview: (review: PacketReview) => void
}

export default function FolderReview({ folder, review, matchedBy, ocrIdentity, rosterIdentity, onReview }: Props) {
  const checks = folder.checks ?? []
  const [selectedCode, setSelectedCode] = useState(checks[0]?.code ?? '')
  const [activeDocId, setActiveDocId] = useState(checks[0]?.evidenceDocId ?? folder.docs[0].id)
  const [activePage, setActivePage] = useState(checks[0]?.source?.page ?? 0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(checks[0]?.source?.bbox ?? null)
  const [lockView, setLockView] = useState(false)

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

  // Focus a checklist row: switch the scan pane to its evidence document, and — for a value
  // check with a located source — jump straight to that page/bbox. Confirm/identity checks
  // just surface the right document with no highlight (nothing on the page to point at).
  const focusCheck = (code: string) => {
    setSelectedCode(code)
    const c = checks.find(x => x.code === code)
    if (!c) return
    setActiveDocId(c.evidenceDocId ?? folder.docs[0]?.id ?? '')
    if (c.kind === 'value' && c.source) { setActivePage(c.source.page); setFocusBbox(c.source.bbox) }
    else { setFocusBbox(null) }   // confirm/identity → show the doc, no highlight
    markSeen(code)
  }

  // Seed the first check as seen on mount, same as focusing it would.
  useEffect(() => { if (checks[0]) markSeen(checks[0].code) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Hotkeys — input-focus + alt/ctrl/meta guards so browser/OS shortcuts (e.g. ⌘F find) pass
  // through untouched. `F` flags the selected check; ↑↓ walk the checklist order; ←→ would
  // step a value check across its sources, but each check has a single source in v1, so that's
  // just a guarded no-op for now.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
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
        const c = checks.find(x => x.code === selectedCode)
        const n = c?.source ? 1 : 0
        if (n < 2) return // single-source checks (v1) — nothing to page through yet
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [checks, selectedCode, review])

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
          onSelect={focusCheck} onToggleFlag={toggleFlag} />
        <EvidenceViewer docs={folder.docs} activeDocId={activeDocId} activePage={activePage}
          focusBbox={focusBbox} lockView={lockView}
          onSelectDoc={id => { setActiveDocId(id); setFocusBbox(null) }}
          onSelectPage={p => { setActivePage(p); setFocusBbox(null) }}
          onToggleLock={() => setLockView(v => !v)}
          rosterLabel={sel?.label}
          rosterValue={sel?.kind === 'value' ? sel.reference : null} />
      </div>
      <ActionBar done={review.done} seenCount={seenCount} total={codes.length}
        hint="↑↓ mục · ←→ tài liệu · F đánh dấu · B khung · V bảng kê · ⌥P di chuyển · ? phím tắt"
        onFinish={() => { if (codes.length > 0 && allSeen(review, codes)) onReview({ ...review, done: true }) }} />
    </div>
  )
}
