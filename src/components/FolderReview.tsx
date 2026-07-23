import { useEffect, useMemo, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvFolder } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import type { PacketReview, FieldFlag, MatchedBy, Identity } from '../upload/api'
import { allSeen } from '../logic/review'
import FolderFieldsPanel from './FolderFieldsPanel'
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
  const ranked = useMemo(() => rankFolder(folder), [folder])
  const first = ranked[0]?.field
  const [selectedKey, setSelectedKey] = useState(first?.key ?? '')
  const [srcIdx, setSrcIdx] = useState(0)
  const [activeDocId, setActiveDocId] = useState(first?.sources[0]?.docId ?? folder.docs[0].id)
  const [activePage, setActivePage] = useState(first?.sources[0]?.page ?? 0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(first?.sources[0]?.bbox ?? null)
  const [lockView, setLockView] = useState(false)

  // Mark a field as seen the first time it's focused — a no-op (no onReview call) if it's
  // already seen, so re-focusing / the mount-seed effect below never loops.
  const markSeen = (key: string) => {
    if (review.fields[key]?.seen) return
    onReview({
      ...review,
      fields: { ...review.fields, [key]: { seen: true, flag: review.fields[key]?.flag ?? null } },
    })
  }

  // Seed the first ranked field as seen on mount, same as focusing it would.
  useEffect(() => { if (first) markSeen(first.key) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleFlag = (key: string, flag: FieldFlag | null) => {
    onReview({ ...review, fields: { ...review.fields, [key]: { seen: true, flag } } })
  }

  // Focus the idx-th source (document) of a field, or clear the highlight if it has none.
  const focusAt = (key: string, idx: number) => {
    setSelectedKey(key)
    setSrcIdx(idx)
    markSeen(key)
    const s = folder.fields.find(f => f.key === key)?.sources[idx]
    if (s) { setActiveDocId(s.docId); setActivePage(s.page); setFocusBbox(s.bbox) }
    else setFocusBbox(null)
  }

  // Switching document by tab (#006): if the currently selected field has a source on the
  // newly-active document, jump straight to it (same as clicking that source's chip) so
  // walking a field across its documents is one click per doc, eye always guided. Only clear
  // the highlight when the field genuinely has no source there.
  const onSelectDoc = (id: string) => {
    const idx = folder.fields.find(f => f.key === selectedKey)?.sources.findIndex(s => s.docId === id) ?? -1
    if (idx >= 0) focusAt(selectedKey, idx)
    else { setActiveDocId(id); setActivePage(0); setFocusBbox(null) }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const i = ranked.findIndex(r => r.field.key === selectedKey)
        const next = e.key === 'ArrowDown' ? Math.min(i + 1, ranked.length - 1) : Math.max(i - 1, 0)
        focusAt(ranked[next].field.key, 0) // new field → first source
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const n = folder.fields.find(f => f.key === selectedKey)?.sources.length ?? 0
        if (n < 2) return // nothing to step through
        e.preventDefault()
        const next = e.key === 'ArrowRight' ? Math.min(srcIdx + 1, n - 1) : Math.max(srcIdx - 1, 0)
        focusAt(selectedKey, next) // same field → next document
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ranked, selectedKey, srcIdx, folder])

  // `F` toggles a flag on the currently selected field — separate from the arrow-nav effect
  // above, same input-focus guard, plus skipping modified keystrokes so browser/OS shortcuts
  // (e.g. ⌘F find) pass through untouched.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        const cur = review.fields[selectedKey]?.flag
        toggleFlag(selectedKey, cur ? null : { reason: '', note: '' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [review, selectedKey])

  const selField = folder.fields.find(f => f.key === selectedKey)
  const fieldKeys = folder.fields.map(f => f.key)
  const seenCount = fieldKeys.filter(k => review.fields[k]?.seen).length

  return (
    <div className="screen">
      <header className="screen-head">
        <div><strong>{folder.heading ?? 'Hồ sơ CTV'} · {folder.name}</strong> — {folder.product}</div>
        <MatchKeyStrip matchedBy={matchedBy} ocr={ocrIdentity} roster={rosterIdentity} />
      </header>
      <div className="panes">
        <FolderFieldsPanel
          ranked={ranked}
          docs={folder.docs}
          selectedKey={selectedKey}
          onSelect={key => focusAt(key, 0)}
          onFocusSource={focusAt}
          review={review}
          onToggleFlag={toggleFlag}
        />
        <EvidenceViewer
          docs={folder.docs}
          activeDocId={activeDocId}
          activePage={activePage}
          focusBbox={focusBbox}
          lockView={lockView}
          onSelectDoc={onSelectDoc}
          onSelectPage={p => { setActivePage(p); setFocusBbox(null) }}
          onToggleLock={() => setLockView(v => !v)}
          rosterLabel={selField?.label}
          rosterValue={selField?.expected ?? null}
        />
      </div>
      <ActionBar
        done={review.done}
        seenCount={seenCount}
        total={fieldKeys.length}
        hint="↑↓ chuyển trường · ←→ đổi chứng từ · F đánh dấu · B khung · V giá trị bảng kê · ⌥P di chuyển · ? phím tắt"
        onFinish={() => { if (allSeen(review, fieldKeys)) onReview({ ...review, done: true }) }}
      />
    </div>
  )
}
