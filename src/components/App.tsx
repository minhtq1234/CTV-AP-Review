import UploadFlow from './UploadFlow'

// The app is the case-management flow: upload a scanned submission, watch it
// split + OCR, then review each CTV packet with decisions that persist.
// (The earlier standalone demos — flight bookings, synthetic CTV folders, the
// receipts demo — have been retired from the UI; their components/data remain
// in the tree but are no longer routed.)
export default function App() {
  return (
    <div className="app">
      <UploadFlow />
    </div>
  )
}
