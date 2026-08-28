import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { fetchPacketManifest } from '../upload/api'
import type { EvidenceDoc } from '../ctv/types'
import EvidenceViewer from './EvidenceViewer'

interface Props {
  caseId: string
  packetIndex: number
  /** Shown in the dialog title so the reviewer knows whose documents these are. */
  packetName: string
  onClose: () => void
  /** The way to continue into the full reviewer from inside the popup. */
  onOpenPacket: (index: number) => void
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'loaded'; docs: EvidenceDoc[] }

const LOAD_ERROR = 'Không tải được chứng từ của gói này.'

/**
 * A quick, read-only look at one packet's evidence documents from the packet
 * list -- so a reviewer can sanity-check "does this packet have what it
 * should" without leaving the list for the full reviewer. No review actions,
 * no mutation, nothing that writes.
 *
 * Reuses EvidenceViewer exactly as the full reviewer does, in its overview
 * presentation: there is no field selection here to focus a value against, so
 * `focusBbox` stays null and `lockView` stays false for the dialog's whole
 * life. Overview mode already makes lock view a no-op (see EvidenceViewer's
 * own `hideLockControl` doc comment), so its toggle is omitted here rather
 * than shown inert.
 *
 * Backdrop-click + Escape follow CccdCardPicker's pattern. styles.css's
 * .packet-docs-backdrop deliberately mirrors .cccd-picker-backdrop's rules
 * rather than reusing that class directly -- it is named for a different
 * feature. The in-flight-fetch guard follows CccdReviewScreen's
 * liveCaseIdRef pattern, keyed on `caseId:packetIndex` since either could
 * change under an already-mounted dialog.
 */
export default function PacketDocsDialog({
  caseId,
  packetIndex,
  packetName,
  onClose,
  onOpenPacket,
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [activeDocId, setActiveDocId] = useState<string | null>(null)
  const [activePage, setActivePage] = useState(0)
  const titleId = useId()

  // What the in-flight request was issued for -- null once retired. Every
  // response is checked against it before touching state, so a `caseId` or
  // `packetIndex` change under a mounted dialog (or an unmount) retires the
  // answer instead of rendering one packet's documents under another's title.
  const liveKeyRef = useRef<string | null>(null)

  const load = useCallback(() => {
    const key = `${caseId}:${packetIndex}`
    liveKeyRef.current = key
    setState({ status: 'loading' })
    fetchPacketManifest(caseId, packetIndex)
      .then(manifest => {
        if (liveKeyRef.current !== key) return
        setState({ status: 'loaded', docs: manifest.docs })
        setActiveDocId(manifest.docs[0]?.id ?? null)
        setActivePage(0)
      })
      .catch(() => {
        if (liveKeyRef.current !== key) return
        setState({ status: 'error' })
      })
  }, [caseId, packetIndex])

  useEffect(() => {
    load()
    return () => { liveKeyRef.current = null }
  }, [load])

  return (
    <div
      className="packet-docs-backdrop"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className="packet-docs-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={event => { if (event.key === 'Escape') onClose() }}
      >
        <header className="packet-docs-head">
          <h2 id={titleId}>Chứng từ — {packetName}</h2>
          <button type="button" onClick={onClose}>Đóng</button>
        </header>

        {state.status === 'loading' && (
          <div className="packet-docs-state">Đang tải…</div>
        )}

        {state.status === 'error' && (
          <div className="packet-docs-state">
            <p className="packet-docs-error-text" role="alert">{LOAD_ERROR}</p>
            <button type="button" className="btn" onClick={load}>Thử lại</button>
          </div>
        )}

        {state.status === 'loaded' && (
          state.docs.length === 0 || !activeDocId ? (
            <div className="packet-docs-state">Gói này chưa có chứng từ nào.</div>
          ) : (
            <EvidenceViewer
              docs={state.docs}
              activeDocId={activeDocId}
              activePage={activePage}
              focusBbox={null}
              lockView={false}
              overviewMode
              overviewResetVersion={0}
              onSelectDoc={id => { setActiveDocId(id); setActivePage(0) }}
              onToggleLock={() => {}}
              // Lock view only gates behaviour overview mode already skips
              // (see EvidenceViewer's own note on this prop) -- overview mode
              // is permanent here, so the toggle would be a control that
              // visibly does nothing. Omit it rather than ship it inert.
              hideLockControl
            />
          )
        )}

        <footer className="packet-docs-foot">
          <button
            type="button"
            className="btn primary"
            onClick={() => onOpenPacket(packetIndex)}
          >
            Mở gói hồ sơ
          </button>
        </footer>
      </section>
    </div>
  )
}
