import type { Verdict } from '../types'
import type { RankedField } from '../logic/verdict'

interface FieldsPanelProps { ranked: RankedField[]; selectedKey: string; onSelect: (key: string) => void }

const CHIP: Record<Verdict, { cls: string; glyph: string }> = {
  mismatch: { cls: 'v-mismatch', glyph: '✗' },
  low_conf: { cls: 'v-low', glyph: '!' },
  fuzzy: { cls: 'v-fuzzy', glyph: '~' },
  match: { cls: 'v-match', glyph: '✓' },
}

export default function FieldsPanel({ ranked, selectedKey, onSelect }: FieldsPanelProps) {
  const n = (v: Verdict) => ranked.filter(r => r.verdict === v).length
  return (
    <aside className="fields-pane">
      <div className="fields-summary">
        <span>{ranked.length} trường</span>
        {n('mismatch') > 0 && <span className="s-mismatch">● {n('mismatch')} lệch</span>}
        {n('low_conf') > 0 && <span className="s-low">● {n('low_conf')} tin cậy thấp</span>}
      </div>
      {ranked.map(r => {
        const c = CHIP[r.verdict]
        const actual = r.field.prediction?.value ?? '—'
        const conf = r.field.prediction ? Math.round(r.field.prediction.confidence * 100) : null
        return (
          <div key={r.field.key} className={`frow ${r.field.key === selectedKey ? 'sel' : ''}`}
            onClick={() => onSelect(r.field.key)}>
            <span className={`chip ${c.cls}`}>{c.glyph}</span>
            <span className="fbody">
              <span className="flabel">{r.field.label}</span>
              <span className="fvals">
                {r.field.expected} → <span className={r.verdict === 'mismatch' ? 'act bad' : 'act'}>{actual}</span>
              </span>
            </span>
            {conf !== null && <span className={`conf ${r.verdict === 'low_conf' ? 'low' : ''}`}>{conf}%</span>}
          </div>
        )
      })}
    </aside>
  )
}
