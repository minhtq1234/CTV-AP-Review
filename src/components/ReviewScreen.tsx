import { useEffect, useState } from 'react'
import type { Case } from '../types'
import { orderFields } from '../logic/verdict'

interface ReviewScreenProps { case_: Case; onUpdateCase: (c: Case) => void }

export default function ReviewScreen({ case_ }: ReviewScreenProps) {
  const ranked = orderFields(case_.fields)
  const [selectedKey, setSelectedKey] = useState(ranked[0]?.field.key ?? '')
  const [page, setPage] = useState(0)

  const selected = case_.fields.find(f => f.key === selectedKey) ?? null

  useEffect(() => {
    if (selected?.prediction) setPage(selected.prediction.page)
  }, [selectedKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
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
        <aside className="fields-pane">
          {ranked.map(r => (
            <div key={r.field.key}
              className={r.field.key === selectedKey ? 'frow sel' : 'frow'}
              onClick={() => setSelectedKey(r.field.key)}>
              {r.field.label}: {r.field.expected} → {r.field.prediction?.value ?? '—'} [{r.verdict}]
            </div>
          ))}
        </aside>
        <section className="doc-pane">
          <img src={case_.pages[page].src} alt="" style={{ maxWidth: '100%' }} />
        </section>
      </div>
    </div>
  )
}
