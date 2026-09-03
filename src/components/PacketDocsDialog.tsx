import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { fetchPacketManifest } from '../upload/api'
import type { EvidenceDoc, EvidenceKind } from '../ctv/types'
import type { Bbox } from '../types'
import EvidenceViewer from './EvidenceViewer'

interface Props {
  caseId: string
  packetIndex: number
  /** Shown in the dialog title so the reviewer knows whose documents these are. */
  packetName: string
  onClose: () => void
  /** The way to continue into the full reviewer from inside the popup. Absent
   *  when the dialog is opened from inside the packet itself -- there is
   *  nowhere to go, and a button that navigates to where you already are is a
   *  lie. */
  onOpenPacket?: (index: number) => void
  /** Open on this exact document. Wins over `initialDocKind` when both are
   *  given; falls back to the first document when the id is not in the packet. */
  initialDocId?: string
  /** Open on this document rather than the first. Falls back to the first when
   *  the packet has no document of that kind. */
  initialDocKind?: EvidenceKind
  /** The cell's own note and value, shown in the header. The matrix cell used
   *  to open a detail row so the reviewer read these before deciding; carrying
   *  them here keeps that, rather than dropping it. */
  context?: { label: string; note?: string; value?: string } | null
  /** Where on the document the criterion says to look — the signature block
   *  for #21–#25, recorded during the read. Outlined, never scrolled to: ver-3
   *  scope §2 decided this popup does not autofocus. A criterion with no box
   *  still names a page, so the page is honoured even when the bbox is null. */
  focus?: { page: number; bbox: Bbox | null } | null
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
 * presentation, and `lockView` stays false for the dialog's whole life.
 * Overview mode already makes lock view a no-op (see EvidenceViewer's own
 * `hideLockControl` doc comment), so its toggle is omitted here rather than
 * shown inert.
 *
 * It does outline a box when one is given. There was no field selection here
 * to focus against, but a criterion cell brings its own answer: #21-#25 record
 * where each party signs, and a tool whose premise is that it points should
 * point. It is drawn and never scrolled to (`showFocusInOverview`), because
 * ver-3 scope §2 decided this popup must not autofocus.
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
  initialDocId,
  focus,
  initialDocKind,
  context,
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
        // Open on the kind the caller asked for -- the matrix cell names the
        // document its column refers to -- falling back to the first when this
        // packet has no document of that kind.
        const requested =
          (initialDocId && manifest.docs.find(doc => doc.id === initialDocId))
          || (initialDocKind && manifest.docs.find(doc => doc.kind === initialDocKind))
          || undefined
        setActiveDocId(requested?.id ?? manifest.docs[0]?.id ?? null)
        setActivePage(focus?.page ?? 0)
      })
      .catch(() => {
        if (liveKeyRef.current !== key) return
        setState({ status: 'error' })
      })
  }, [caseId, packetIndex, initialDocKind, initialDocId, focus?.page])

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

        {/* The cell's note and value. The matrix cell used to open a detail row
            so these were read before deciding; carrying them into the popup
            keeps that rather than reducing the decision to a glyph. */}
        {context && (
          <div className="packet-docs-context">
            <span className="packet-docs-context-lbl">{context.label}</span>
            {context.value && (
              <span className="packet-docs-context-val">{context.value}</span>
            )}
            {context.note && (
              <p className="packet-docs-context-note">{context.note}</p>
            )}
          </div>
        )}


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
              focusBbox={focus?.bbox ?? null}
              showFocusInOverview
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

        {/* Only when there is somewhere to go: opened from inside the packet
            itself, this button would navigate to where the reviewer already is. */}
        {onOpenPacket && (
          <footer className="packet-docs-foot">
            <button
              type="button"
              className="btn primary"
              onClick={() => onOpenPacket(packetIndex)}
            >
              Mở gói hồ sơ
            </button>
          </footer>
        )}
      </section>
    </div>
  )
}
