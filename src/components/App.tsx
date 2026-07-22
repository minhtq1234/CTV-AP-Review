import UploadFlow from './UploadFlow'
import DemoFlow from './DemoFlow'

// The live app is the case-management flow: upload a scanned submission, watch it
// split + OCR, then review each CTV packet with decisions that persist to the backend.
//
// The single-file export can't reach that backend (a file:// document has no server
// and can't inline real, PII-bearing cases), so when it detects the export bundle —
// `window.__ASSETS__`, injected by scripts/build-single.mjs — it runs the offline
// DemoFlow instead: the same reviewer against synthetic, PII-free sample folders.
const isExport = typeof window !== 'undefined'
  && !!(window as { __ASSETS__?: unknown }).__ASSETS__

export default function App() {
  return (
    <div className="app">
      {isExport ? <DemoFlow /> : <UploadFlow />}
    </div>
  )
}
