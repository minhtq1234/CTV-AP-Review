import { useEffect, useMemo, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvField, CtvFolder } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import FolderFieldsPanel from './FolderFieldsPanel'
import EvidenceViewer from './EvidenceViewer'
import ActionBar from './ActionBar'

interface Props { folder: CtvFolder; onUpdate: (f: CtvFolder) => void }

export default function FolderReview({ folder, onUpdate }: Props) {
  const ranked = useMemo(() => rankFolder(folder), [folder])
  const firstSrc = ranked[0]?.field.sources[0]
  const [selectedKey, setSelectedKey] = useState(ranked[0]?.field.key ?? '')
  const [activeDocId, setActiveDocId] = useState(firstSrc?.docId ?? folder.docs[0].id)
  const [activePage, setActivePage] = useState(firstSrc?.page ?? 0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(firstSrc?.bbox ?? null)
  const [lockView, setLockView] = useState(false)

  const focusFirst = (f: CtvField | undefined) => {
    const s = f?.sources[0]
    if (s) { setActiveDocId(s.docId); setActivePage(s.page); setFocusBbox(s.bbox) }
    else setFocusBbox(null)
  }
  const selectField = (key: string) => {
    setSelectedKey(key)
    focusFirst(folder.fields.find(f => f.key === key))
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      e.preventDefault()
      const i = ranked.findIndex(r => r.field.key === selectedKey)
      const next = e.key === 'ArrowDown' ? Math.min(i + 1, ranked.length - 1) : Math.max(i - 1, 0)
      selectField(ranked[next].field.key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ranked, selectedKey])

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
          onSelect={selectField}
          onFocusSource={(docId, page, bbox) => { setActiveDocId(docId); setActivePage(page); setFocusBbox(bbox) }}
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
        onApprove={() => onUpdate({ ...folder, status: 'approved' })}
        onReject={reason => onUpdate({ ...folder, status: 'rejected', rejectReason: reason })}
      />
    </div>
  )
}
