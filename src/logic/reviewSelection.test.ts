import { describe, expect, it } from 'vitest'
import {
  fieldSelection,
  moveVerticalSelection,
  overviewSelection,
  selectedFieldKey,
} from './reviewSelection'

describe('review selection', () => {
  const fieldKeys = ['name', 'cccd', 'fee']

  it('represents Overview without borrowing a field key', () => {
    expect(overviewSelection()).toEqual({ kind: 'overview' })
    expect(selectedFieldKey(overviewSelection())).toBeNull()
    expect(selectedFieldKey(fieldSelection('cccd', 1))).toBe('cccd')
  })

  it('moves down from Overview into the first real field', () => {
    expect(moveVerticalSelection(
      overviewSelection(),
      fieldKeys,
      'down',
    )).toEqual(fieldSelection('name'))
  })

  it('moves up from the first field back to Overview', () => {
    expect(moveVerticalSelection(
      fieldSelection('name'),
      fieldKeys,
      'up',
    )).toEqual(overviewSelection())
  })

  it('keeps normal field-to-field navigation and endpoint clamping', () => {
    expect(moveVerticalSelection(
      fieldSelection('cccd', 1),
      fieldKeys,
      'down',
    )).toEqual(fieldSelection('fee'))
    expect(moveVerticalSelection(
      fieldSelection('cccd', 1),
      fieldKeys,
      'up',
    )).toEqual(fieldSelection('name'))
    expect(moveVerticalSelection(
      fieldSelection('fee'),
      fieldKeys,
      'down',
    )).toEqual(fieldSelection('fee'))
    expect(moveVerticalSelection(
      overviewSelection(),
      fieldKeys,
      'up',
    )).toEqual(overviewSelection())
  })

  it('stays on Overview when there are no real fields', () => {
    expect(moveVerticalSelection(
      overviewSelection(),
      [],
      'down',
    )).toEqual(overviewSelection())
  })
})
