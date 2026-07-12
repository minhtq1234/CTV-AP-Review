import { useEffect, useState } from 'react'
import type { CtvFolder } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import FolderFieldsPanel from './FolderFieldsPanel'
import EvidenceViewer from './EvidenceViewer'
import ActionBar from './ActionBar'

interface Props { folder: CtvFolder; onUpdate: (f: CtvFolder) => void }

export default function FolderReview({ folder, onUpdate }: Props) {
  const ranked = rankFolder(folder)
  const [selectedKey, setSelectedKey] = useState(ranked[0]?.field.key ?? '')
  const selected = folder.fields.find(f => f.key === selectedKey) ?? null
  const [activeDocId, setActiveDocId] = useState(selected?.extract?.docId ?? folder.docs[0].id)
  const [lockView, setLockView] = useState(false)

  useEffect(() => {
    if (selected?.extract) setActiveDocId(selected.extract.docId)
  }, [selectedKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      e.preventDefault()
      const i = ranked.findIndex(r => r.field.key === selectedKey)
      const next = e.key === 'ArrowDown' ? Math.min(i + 1, ranked.length - 1) : Math.max(i - 1, 0)
      setSelectedKey(ranked[next].field.key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ranked, selectedKey])

  const focusBbox = selected?.extract && selected.extract.docId === activeDocId ? selected.extract.bbox : null

  return (
    <div className="screen">
      <header className="screen-head">
        <div><strong>Hồ sơ CTV · {folder.name}</strong> — {folder.product}</div>
        <span className={`status-pill ${folder.status}`}>
          {folder.status === 'pending' ? 'Chờ duyệt' : folder.status === 'approved' ? 'Đã duyệt' : 'Đã từ chối'}
        </span>
      </header>
      <div className="panes">
        <FolderFieldsPanel ranked={ranked} selectedKey={selectedKey} onSelect={setSelectedKey} />
        <EvidenceViewer
          docs={folder.docs}
          activeDocId={activeDocId}
          focusBbox={focusBbox}
          lockView={lockView}
          onSelectDoc={setActiveDocId}
          onToggleLock={() => setLockView(v => !v)}
        />
      </div>
      <ActionBar
        status={folder.status}
        rejectReason={folder.rejectReason}
        onApprove={() => onUpdate({ ...folder, status: 'approved' })}
        onReject={(reason) => onUpdate({ ...folder, status: 'rejected', rejectReason: reason })}
      />
    </div>
  )
}
