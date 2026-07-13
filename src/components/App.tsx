import { useEffect, useState } from 'react'
import type { Case } from '../types'
import { seedCases } from '../data/cases'
import ReviewScreen from './ReviewScreen'
import type { CtvFolder } from '../ctv/types'
import { folders as seedFolders } from '../ctv/folders'
import { flights as seedFlights } from '../ctv/flights'
import { loadManifestFolder } from '../ctv/loadFolder'
import FolderReview from './FolderReview'

type Mode = 'flight' | 'ctv' | 'receipts'

// In CTV mode one folder is loaded at runtime from a manifest.json (the splitter's output shape).
const MANIFEST_URL = '/folders/le-thi-mai-anh/manifest.json'
const HARDCODED = seedFolders.filter(f => f.id !== 'le-thi-mai-anh')

export default function App() {
  const [mode, setMode] = useState<Mode>('flight')
  const [cases, setCases] = useState<Case[]>(seedCases)
  const [caseId, setCaseId] = useState(seedCases[0].id)
  const [folders, setFolders] = useState<CtvFolder[]>(HARDCODED)
  const [manifestId, setManifestId] = useState<string | null>(null)
  const [folderId, setFolderId] = useState(HARDCODED[0].id)
  const [flights, setFlights] = useState<CtvFolder[]>(seedFlights)
  const [flightId, setFlightId] = useState(seedFlights[0].id)

  useEffect(() => {
    loadManifestFolder(MANIFEST_URL)
      .then(mf => {
        setFolders(prev => (prev.some(f => f.id === mf.id) ? prev : [mf, ...prev]))
        setManifestId(mf.id)
      })
      .catch(() => {})
  }, [])

  const curCase = cases.find(c => c.id === caseId)!
  const curFolder = folders.find(f => f.id === folderId) ?? folders[0]
  const curFlight = flights.find(f => f.id === flightId) ?? flights[0]

  return (
    <div className="app">
      <div className="mode-bar">
        <button className={mode === 'flight' ? 'mode on' : 'mode'} onClick={() => setMode('flight')}>Vé máy bay</button>
        <button className={mode === 'ctv' ? 'mode on' : 'mode'} onClick={() => setMode('ctv')}>Hồ sơ CTV</button>
        <button className={mode === 'receipts' ? 'mode on' : 'mode'} onClick={() => setMode('receipts')}>Hoá đơn (demo cũ)</button>
      </div>

      {mode === 'flight' && (
        <>
          <nav className="case-tabs">
            {flights.map(f => (
              <button key={f.id} className={f.id === flightId ? 'tab active' : 'tab'} onClick={() => setFlightId(f.id)}>
                {f.name} · {f.product}
                {f.status !== 'pending' && <span className={`dot ${f.status}`} />}
              </button>
            ))}
          </nav>
          <FolderReview key={curFlight.id} folder={curFlight}
            onUpdate={f => setFlights(prev => prev.map(x => (x.id === f.id ? f : x)))} />
        </>
      )}

      {mode === 'ctv' && (
        <>
          <nav className="case-tabs">
            {folders.map(f => (
              <button key={f.id} className={f.id === folderId ? 'tab active' : 'tab'} onClick={() => setFolderId(f.id)}>
                {f.name} · {f.product}
                {f.id === manifestId && <span className="mf-badge" title="Nạp từ manifest.json (đầu ra của splitter)">manifest</span>}
                {f.status !== 'pending' && <span className={`dot ${f.status}`} />}
              </button>
            ))}
          </nav>
          <FolderReview key={curFolder.id} folder={curFolder}
            onUpdate={f => setFolders(prev => prev.map(x => (x.id === f.id ? f : x)))} />
        </>
      )}

      {mode === 'receipts' && (
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
