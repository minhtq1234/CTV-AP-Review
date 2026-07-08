import { useEffect, useState } from 'react'
import type { Case } from '../types'
import { orderFields } from '../logic/verdict'
import DocViewer from './DocViewer'
import FieldsPanel from './FieldsPanel'
import FieldPalette from './FieldPalette'

interface ReviewScreenProps { case_: Case; onUpdateCase: (c: Case) => void }

export default function ReviewScreen({ case_ }: ReviewScreenProps) {
  const ranked = orderFields(case_.fields)
  const [selectedKey, setSelectedKey] = useState(ranked[0]?.field.key ?? '')
  const [page, setPage] = useState(0)
  const [lockView, setLockView] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)

  const selected = case_.fields.find(f => f.key === selectedKey) ?? null

  useEffect(() => {
    if (selected?.prediction) setPage(selected.prediction.page)
  }, [selectedKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen(true); return }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
      e.preventDefault()
      const i = ranked.findIndex(r => r.field.key === selectedKey)
      const next = e.key === 'ArrowDown' ? Math.min(i + 1, ranked.length - 1) : Math.max(i - 1, 0)
      setSelectedKey(ranked[next].field.key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ranked, selectedKey])

  return (
    <div className="screen">
      <header className="screen-head">
        <div><strong>Đề nghị thanh toán #{case_.id}</strong> — {case_.requester} · {case_.category}</div>
      </header>
      <div className="panes">
        <FieldsPanel ranked={ranked} selectedKey={selectedKey} onSelect={setSelectedKey} />
        <DocViewer
          pages={case_.pages}
          page={page}
          focusBbox={selected?.prediction && selected.prediction.page === page ? selected.prediction.bbox : null}
          lockView={lockView}
          onPageChange={setPage}
          onToggleLock={() => setLockView(v => !v)}
        />
      </div>
      <FieldPalette open={paletteOpen} ranked={ranked}
        onJump={setSelectedKey} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
