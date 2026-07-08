import { useEffect, useState } from 'react'
import type { RankedField } from '../logic/verdict'

interface FieldPaletteProps { open: boolean; ranked: RankedField[]; onJump: (key: string) => void; onClose: () => void }

export default function FieldPalette({ open, ranked, onJump, onClose }: FieldPaletteProps) {
  const [q, setQ] = useState('')
  useEffect(() => { if (open) setQ('') }, [open])
  if (!open) return null
  const rows = ranked.filter(r => r.field.label.toLowerCase().includes(q.toLowerCase()))
  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette" onClick={e => e.stopPropagation()}>
        <input autoFocus placeholder="Nhảy tới trường…" value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') onClose()
            if (e.key === 'Enter' && rows[0]) { onJump(rows[0].field.key); onClose() }
          }} />
        <div className="palette-list">
          {rows.map(r => (
            <div key={r.field.key} className="palette-row"
              onClick={() => { onJump(r.field.key); onClose() }}>
              <span className={`chip v-${r.verdict === 'low_conf' ? 'low' : r.verdict}`} />
              {r.field.label}
              <span className="palette-val">{r.field.prediction?.value ?? '—'}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
