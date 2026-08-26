import { useEffect, useRef } from 'react'
import type { Bbox } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import EvidenceViewer from './EvidenceViewer'

interface Props {
  docs: EvidenceDoc[]
  activeDocId: string
  activePage: number
  focusBbox: Bbox | null
  lockView: boolean
  overviewResetVersion: number
  onSelectDoc: (id: string) => void
  onToggleLock: () => void
  onClose: () => void
  onOpenFull: () => void
  rosterLabel: string
  rosterValue: string | null
}

export default function PacketEvidenceDrawer({
  docs,
  activeDocId,
  activePage,
  focusBbox,
  lockView,
  overviewResetVersion,
  onSelectDoc,
  onToggleLock,
  onClose,
  onOpenFull,
  rosterLabel,
  rosterValue,
}: Props) {
  const drawerRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (!target || drawerRef.current?.contains(target)) return
      // A grid evidence cell both changes the selection and keeps the drawer open.
      if (target.closest('button.packet-grid-status')) return
      onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('mousedown', onPointerDown, true)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('mousedown', onPointerDown, true)
    }
  }, [onClose])

  return (
    <div className="packet-evidence-overlay" aria-hidden="false">
      <aside
        ref={drawerRef}
        className="packet-evidence-drawer"
        role="dialog"
        aria-label={`Chứng từ — ${rosterLabel}`}
      >
        <header className="packet-evidence-header">
          <div>
            <span>Đối chiếu chứng từ</span>
            <strong>{rosterLabel}</strong>
          </div>
          <div className="packet-evidence-actions">
            <button type="button" className="btn" onClick={onOpenFull}>
              Mở toàn màn hình
            </button>
            <button
              type="button"
              className="packet-evidence-close"
              aria-label="Đóng xem chứng từ"
              onClick={onClose}
            >
              ×
            </button>
          </div>
        </header>
        <EvidenceViewer
          docs={docs}
          activeDocId={activeDocId}
          activePage={activePage}
          focusBbox={focusBbox}
          lockView={lockView}
          overviewMode={false}
          overviewResetVersion={overviewResetVersion}
          onSelectDoc={onSelectDoc}
          onToggleLock={onToggleLock}
          rosterLabel={rosterLabel}
          rosterValue={rosterValue}
        />
      </aside>
    </div>
  )
}
