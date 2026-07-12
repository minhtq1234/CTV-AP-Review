import { useState } from 'react'
import type { Case } from '../types'
import { seedCases } from '../data/cases'
import ReviewScreen from './ReviewScreen'
import type { CtvFolder } from '../ctv/types'
import { folders as seedFolders } from '../ctv/folders'
import FolderReview from './FolderReview'

type Mode = 'ctv' | 'receipts'

export default function App() {
  const [mode, setMode] = useState<Mode>('ctv')
  const [cases, setCases] = useState<Case[]>(seedCases)
  const [folders, setFolders] = useState<CtvFolder[]>(seedFolders)
  const [caseId, setCaseId] = useState(seedCases[0].id)
  const [folderId, setFolderId] = useState(seedFolders[0].id)

  const curCase = cases.find(c => c.id === caseId)!
  const curFolder = folders.find(f => f.id === folderId)!

  return (
    <div className="app">
      <div className="mode-bar">
        <button className={mode === 'ctv' ? 'mode on' : 'mode'} onClick={() => setMode('ctv')}>Hồ sơ CTV</button>
        <button className={mode === 'receipts' ? 'mode on' : 'mode'} onClick={() => setMode('receipts')}>Hoá đơn (demo cũ)</button>
      </div>

      {mode === 'ctv' ? (
        <>
          <nav className="case-tabs">
            {folders.map(f => (
              <button key={f.id} className={f.id === folderId ? 'tab active' : 'tab'} onClick={() => setFolderId(f.id)}>
                {f.name} · {f.product}
                {f.status !== 'pending' && <span className={`dot ${f.status}`} />}
              </button>
            ))}
          </nav>
          <FolderReview key={curFolder.id} folder={curFolder}
            onUpdate={f => setFolders(prev => prev.map(x => (x.id === f.id ? f : x)))} />
        </>
      ) : (
        <>
          <nav className="case-tabs">
            {cases.map(c => (
              <button key={c.id} className={c.id === caseId ? 'tab active' : 'tab'} onClick={() => setCaseId(c.id)}>
                {c.id} · {c.category}
                {c.status !== 'pending' && <span className={`dot ${c.status}`} />}
              </button>
            ))}
          </nav>
          <ReviewScreen key={curCase.id} case_={curCase}
            onUpdateCase={c => setCases(prev => prev.map(x => (x.id === c.id ? c : x)))} />
        </>
      )}
    </div>
  )
}
