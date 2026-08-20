import { describe, expect, it } from 'vitest'
import type { CtvFolder } from '../ctv/types'
import { buildPacketGrid } from './packetGrid'

const folder: CtvFolder = {
  id: 'grid-fixture',
  name: 'Synthetic reviewer',
  product: 'Synthetic product',
  status: 'pending',
  exempt: false,
  docs: [
    {
      id: 'contract',
      kind: 'contract',
      label: 'Hợp đồng',
      pages: [{ src: '/contract.svg', width: 1000, height: 1400 }],
    },
    {
      id: 'pit',
      kind: 'pit',
      label: 'Website thuế',
      pages: [{ src: '/pit.svg', width: 1000, height: 1400 }],
    },
  ],
  fields: [
    {
      key: 'name',
      label: 'Họ và tên',
      group: 'Danh tính',
      check: 'compare',
      kind: 'name',
      expected: 'Nguyen Van A',
      sources: [
        {
          docId: 'contract', page: 0, value: 'Nguyen Van A', confidence: 0.99,
          bbox: { x: 10, y: 20, width: 100, height: 20 },
        },
        {
          docId: 'pit', page: 0, value: 'Nguyen Van A', confidence: 0.5,
          bbox: { x: 15, y: 25, width: 100, height: 20 },
        },
      ],
    },
    {
      key: 'cccd',
      label: 'Số CCCD',
      group: 'Danh tính',
      check: 'compare',
      kind: 'text',
      expected: '123',
      sources: [{
        docId: 'contract', page: 0, value: '456', confidence: 0.99,
        bbox: { x: 10, y: 50, width: 100, height: 20 },
      }],
    },
    {
      key: 'dob',
      label: 'Ngày sinh',
      group: 'Danh tính',
      check: 'compare',
      kind: 'date',
      expected: '01/01/2000',
      sources: [],
    },
  ],
}

describe('packet grid model', () => {
  it('derives dynamic document columns and per-source statuses', () => {
    const grid = buildPacketGrid(folder)

    expect(grid.columns).toEqual([
      { docId: 'contract', label: 'Hợp đồng' },
      { docId: 'pit', label: 'Website thuế' },
    ])
    expect(grid.rows.map(row => ({
      fieldKey: row.fieldKey,
      statuses: row.cells.map(cell => cell.status),
    }))).toEqual([
      { fieldKey: 'name', statuses: ['match', 'review'] },
      { fieldKey: 'cccd', statuses: ['mismatch', 'na'] },
      { fieldKey: 'dob', statuses: ['na', 'na'] },
    ])
  })

  it('summarizes each document using its most severe populated cell', () => {
    expect(buildPacketGrid(folder).summaries).toEqual([
      { docId: 'contract', status: 'mismatch' },
      { docId: 'pit', status: 'review' },
    ])
  })

  it('retains the source index needed to open exact evidence', () => {
    const grid = buildPacketGrid(folder)

    expect(grid.rows[0].cells).toEqual([
      { status: 'match', sourceIndex: 0 },
      { status: 'review', sourceIndex: 1 },
    ])
    expect(grid.rows[2].cells[0]).toEqual({ status: 'na' })
  })

  it('keeps empty packets reviewable instead of crashing the grid', () => {
    const grid = buildPacketGrid({ ...folder, fields: [] })

    expect(grid.rows).toEqual([])
    expect(grid.summaries).toEqual([
      { docId: 'contract', status: 'na' },
      { docId: 'pit', status: 'na' },
    ])
  })
})
