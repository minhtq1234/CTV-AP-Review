import { describe, expect, it } from 'vitest'
import type { CtvFolder, EvidenceKind } from '../ctv/types'
import { summarizePacketEvidence } from './packetEvidenceSummary'

const page = { src: '/synthetic.png', width: 100, height: 100 }

function folder(
  kinds: EvidenceKind[],
  source: { value: string; confidence: number } = { value: '123', confidence: 0.99 },
): CtvFolder {
  return {
    id: 'synthetic-folder',
    name: 'Synthetic Person',
    product: 'Synthetic Product',
    status: 'pending',
    exempt: false,
    docs: kinds.map((kind, index) => ({
      id: `doc-${index}`,
      kind,
      label: `Synthetic ${kind}`,
      pages: [page],
    })),
    fields: [{
      key: 'synthetic-field',
      label: 'Synthetic field',
      group: 'Danh tính',
      check: 'compare',
      kind: 'text',
      expected: '123',
      sources: [{
        docId: 'doc-2',
        page: 0,
        value: source.value,
        confidence: source.confidence,
        bbox: { x: 0, y: 0, width: 10, height: 10 },
      }],
    }],
  }
}

describe('packet evidence summary', () => {
  it('recognizes a commitment kind and reports a complete five-document packet', () => {
    const result = summarizePacketEvidence(folder([
      'id_front', 'id_back', 'contract', 'bbnt', 'appendix', 'commitment',
    ]))

    expect(result).toEqual({
      taxCommitmentDetected: true,
      documents: { present: 5, total: 5, missing: [] },
      aiResult: 'match',
    })
  })

  it('fails document completeness and AI result when a baseline document is missing', () => {
    const result = summarizePacketEvidence(folder([
      'id_front', 'id_back', 'contract', 'appendix',
    ]))

    expect(result).toEqual({
      taxCommitmentDetected: false,
      documents: { present: 3, total: 4, missing: ['BBNT'] },
      aiResult: 'mismatch',
    })
  })

  it('maps a low-confidence field to review when required documents are complete', () => {
    const result = summarizePacketEvidence(folder(
      ['id_front', 'id_back', 'contract', 'bbnt', 'appendix'],
      { value: '123', confidence: 0.4 },
    ))

    expect(result.documents).toEqual({ present: 4, total: 4, missing: [] })
    expect(result.aiResult).toBe('review')
  })

  it('maps a field mismatch to mismatch when required documents are complete', () => {
    const result = summarizePacketEvidence(folder(
      ['id_front', 'id_back', 'contract', 'bbnt', 'appendix'],
      { value: '999', confidence: 0.99 },
    ))

    expect(result.aiResult).toBe('mismatch')
  })

  it('forces review when packet boundaries are unresolved', () => {
    const result = summarizePacketEvidence(folder([
      'id_front', 'id_back', 'contract', 'bbnt', 'appendix',
    ]), {
      status: 'review',
      suspectedMultiplePackets: true,
      reasons: ['multiple-contract-starts'],
      candidateStarts: [121, 129],
    })

    expect(result.aiResult).toBe('review')
  })

  it('reviews packet grouping before evaluating an otherwise invalid packet', () => {
    const result = summarizePacketEvidence(folder([
      'id_front', 'id_back', 'contract', 'appendix',
    ]), {
      status: 'review',
      suspectedMultiplePackets: true,
      reasons: ['multiple-contract-starts'],
      candidateStarts: [121, 129],
    })

    expect(result.documents.missing).toEqual(['BBNT'])
    expect(result.aiResult).toBe('review')
  })
})
