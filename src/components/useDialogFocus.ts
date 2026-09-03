import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/** Make a `role="dialog"` actually behave like one: focus in, focus back,
 *  Escape, and a Tab trap.
 *
 * Both CCCD dialogs declared `role="dialog" aria-modal="true"` and did none of
 * it, and the tab-order consequence was not cosmetic. Measured in Chrome on a
 * real 25-packet case with the picker open: 70 tab stops document-wide, the
 * first control *inside* the dialog at 51 — and `Tiếp tục`, the hard gate off
 * the screen, at 50. So Tab reached the gate immediately before the dialog,
 * behind a 48%-dim backdrop, and activating it advanced the case with 18 cards
 * still unassigned.
 *
 * Escape binds on `window`, not on the panel's own `onKeyDown`. A browser
 * fires keydown at the focused element; nothing was ever focused inside the
 * panel, so React's synthetic bubbling never reached the handler that was
 * already written there. Verified: Escape dispatched at `document.activeElement`,
 * at `document.body` and at the backdrop all left the dialog mounted.
 *
 * The panel itself takes focus rather than its first button, so a screen
 * reader announces the dialog and an immediate Enter cannot dismiss it. The
 * panel therefore needs `tabIndex={-1}`.
 */
export function useDialogFocus(
  panel: RefObject<HTMLElement | null>,
  onClose: () => void,
): void {
  // Kept in a ref so a new closure each render does not re-run the effect and
  // steal focus back from whatever the reviewer has since tabbed to.
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    const returnTo = document.activeElement as HTMLElement | null
    panel.current?.focus()

    const stops = () =>
      Array.from(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
        .filter(node => node.offsetParent !== null)

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        close.current()
        return
      }
      if (event.key !== 'Tab' || !panel.current) return
      const inside = stops()
      if (!inside.length) {
        event.preventDefault()
        panel.current.focus()
        return
      }
      const first = inside[0]
      const last = inside[inside.length - 1]
      const active = document.activeElement
      const leaving = event.shiftKey
        ? active === first || active === panel.current
        : active === last
      if (leaving || !panel.current.contains(active)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      }
    }

    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      window.removeEventListener('keydown', onKeyDown, true)
      // Only if it still exists: after an assign, the row whose button opened
      // the picker has been removed from the queue.
      if (returnTo?.isConnected) returnTo.focus()
    }
  }, [panel])
}
