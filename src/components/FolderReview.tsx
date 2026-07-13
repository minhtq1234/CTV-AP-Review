import { useEffect, useMemo, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvFolder } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import FolderFieldsPanel from './FolderFieldsPanel'
import EvidenceViewer from './EvidenceViewer'
import ActionBar from './ActionBar'

interface Props { folder: CtvFolder; onUpdate: (f: CtvFolder) => void }

export default function FolderReview({ folder, onUpdate }: Props) {
  const ranked = useMemo(() => rankFolder(folder), [folder])
  const first = ranked[0]?.field
  const [selectedKey, setSelectedKey] = useState(first?.key ?? '')
  const [srcIdx, setSrcIdx] = useState(0)
  const [activeDocId, setActiveDocId] = useState(first?.sources[0]?.docId ?? folder.docs[0].id)
  const [activePage, setActivePage] = useState(first?.sources[0]?.page ?? 0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(first?.sources[0]?.bbox ?? null)
  const [lockView, setLockView] = useState(false)

  // Focus the idx-th source (document) of a field, or clear the highlight if it has none.
  const focusAt = (key: string, idx: number) => {
    setSelectedKey(key)
    setSrcIdx(idx)
    const s = folder.fields.find(f => f.key === key)?.sources[idx]
    if (s) { setActiveDocId(s.docId); setActivePage(s.page); setFocusBbox(s.bbox) }
    else setFocusBbox(null)
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

  return (
    <div className="screen">
      <header className="screen-head">
        <div><strong>Hồ sơ CTV · {folder.name}</strong> — {folder.product}</div>
        <span className={`status-pill ${folder.status}`}>
          {folder.status === 'pending' ? 'Chờ duyệt' : folder.status === 'approved' ? 'Đã duyệt' : 'Đã từ chối'}
        </span>
      </header>
      <div className="panes">
        <FolderFieldsPanel
          ranked={ranked}
          docs={folder.docs}
          selectedKey={selectedKey}
          onSelect={key => focusAt(key, 0)}
          onFocusSource={focusAt}
        />
        <EvidenceViewer
          docs={folder.docs}
          activeDocId={activeDocId}
          activePage={activePage}
          focusBbox={focusBbox}
          lockView={lockView}
          onSelectDoc={id => { setActiveDocId(id); setActivePage(0); setFocusBbox(null) }}
          onSelectPage={p => { setActivePage(p); setFocusBbox(null) }}
          onToggleLock={() => setLockView(v => !v)}
        />
      </div>
      <ActionBar
        status={folder.status}
        rejectReason={folder.rejectReason}
        hint="↑↓ chuyển trường · ←→ đổi chứng từ · Alt +/− phóng to"
        onApprove={() => onUpdate({ ...folder, status: 'approved' })}
        onReject={reason => onUpdate({ ...folder, status: 'rejected', rejectReason: reason })}
      />
    </div>
  )
}
