import { describe, it, expect } from 'vitest'
import { demoChecklist } from './demoChecklist'
import type { CtvFolder, EvidenceDoc } from './types'

const baseDoc = (id: string, kind: EvidenceDoc['kind']): EvidenceDoc =>
  ({ id, kind, label: id, pages: [{ src: `/x/${id}.svg`, width: 10, height: 10 }] })

const folder = (docs: EvidenceDoc[]): CtvFolder => ({
  id: 'f', name: 'N', product: 'P', status: 'pending', exempt: false,
  docs, fields: [],
})

const byCode = (folderArg: CtvFolder) =>
  Object.fromEntries(demoChecklist(folderArg).map(c => [c.code, c]))

describe('demoChecklist C1 routing', () => {
  it('routes C1 to the appendix (Phụ lục) when present', () => {
    const c = byCode(folder([baseDoc('contract', 'contract'), baseDoc('bbnt', 'bbnt'), baseDoc('pluc', 'appendix')]))
    expect(c['C1'].evidenceDocId).toBe('pluc')
    expect(c['C1'].kind).toBe('confirm')
  })
  it('falls back to the bbnt when there is no appendix', () => {
    const c = byCode(folder([baseDoc('contract', 'contract'), baseDoc('bbnt', 'bbnt')]))
    expect(c['C1'].evidenceDocId).toBe('bbnt')
  })
})
