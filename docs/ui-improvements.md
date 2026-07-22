# UI improvements backlog

Enhancement requests for the reviewer UI (not bugs). Captured for later; none
implemented yet. Existing shortcuts today: `↑/↓` move between fields, `←/→` step
across a field's documents, `Alt +/−` zoom.

| # | Improvement | Where | Hotkey |
|---|-------------|-------|--------|
| U1 | Enlarge the highlight bbox ~20% on all sides | EvidenceViewer overlay (+ loupe frame) | — |
| U2 | Toggle the bbox highlight on/off | EvidenceViewer toolbar | `B` (proposed) |
| U3 | Color the pills/tabs in the doc view so they stand out | EvidenceViewer doc tabs | — |
| U4 | Add a Pan tool | EvidenceViewer toolbar | `Option/Alt + P` |
| U5 | Show a list of available hotkeys | a help overlay/legend | `?` (proposed) |

---

## U1 — Bbox 20% larger on all sides
When drawing the red highlight rectangle (and when computing the loupe focus
frame), inflate the field's bbox by ~20% on each side so the boxed area includes
more surrounding context and is easier to read. Implement in
`src/components/EvidenceViewer.tsx` (the overlay rect) and, if the framing should
follow, in `src/logic/loupe.ts` (`loupeFrame`/`boxToviewport`). Keep the inflation
clamped to the page bounds.

## U2 — Toggle bbox on/off (+ hotkey)
A toolbar button in the doc view to show/hide the highlight overlay, so the
reviewer can see the underlying document unobstructed. Add a keyboard shortcut
(proposed `B` for "box"; guard against firing while typing in an input). State is
local to `EvidenceViewer`. Add it to the U5 hotkey legend.

## U3 — Color the doc-view pills/tabs
The document-switcher tabs in the right pane (e.g. "Hợp đồng dịch vụ", "Biên bản
thanh lý hợp đồng", "Tra cứu thuế") are currently plain/monochrome. Give them
color so the active + available documents stand out — e.g. an accent for the
active tab and a subtle tint per document, or color by document kind. Style in
`src/styles.css` + `EvidenceViewer.tsx`.

## U4 — Pan tool (Option/Alt + P)
Add an explicit Pan button to the doc-view toolbar and a `Option/Alt + P` hotkey
to toggle pan mode (drag to move the zoomed document). Check whether drag-pan
already exists in `EvidenceViewer`; if so this is a visible toggle + shortcut over
it, otherwise implement drag-to-pan. Add to the U5 legend.

## U5 — Hotkey reference
A discoverable list of all shortcuts — either a small always-visible legend or a
`?`-triggered overlay. Should cover: `↑/↓` fields, `←/→` documents, `Alt +/−`
zoom, `B` toggle box (U2), `Option/Alt + P` pan (U4), and lock-view. The
`ActionBar` already shows a short hint string — this extends it into a full
reference.

## Notes
- U1–U4 are localized to the doc viewer (`EvidenceViewer.tsx` + `styles.css`);
  U5 spans the viewer + a legend component.
- Keyboard handlers must ignore key events when focus is in an INPUT/TEXTAREA
  (the existing field-nav handler already does this — follow that pattern).
- Proposed keys (`B`, `?`) are suggestions; confirm before wiring.
