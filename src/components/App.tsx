import { useState } from 'react'
import type { Case } from '../types'
import { seedCases } from '../data/cases'
import ReviewScreen from './ReviewScreen'

export default function App() {
  const [cases, setCases] = useState<Case[]>(seedCases)
  const [selectedId, setSelectedId] = useState(cases[0].id)
  const current = cases.find(c => c.id === selectedId)!
  const updateCase = (c: Case) => setCases(prev => prev.map(x => (x.id === c.id ? c : x)))

  return (
    <div className="app">
      <nav className="case-tabs">
        {cases.map(c => (
          <button key={c.id} className={c.id === selectedId ? 'tab active' : 'tab'}
            onClick={() => setSelectedId(c.id)}>
            {c.id} · {c.category}
            {c.status !== 'pending' && <span className={`dot ${c.status}`} />}
          </button>
        ))}
      </nav>
      <ReviewScreen key={current.id} case_={current} onUpdateCase={updateCase} />
    </div>
  )
}
