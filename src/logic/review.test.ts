import { test, expect } from 'vitest'
import { allSeen, packetStatus, calloutAnchor } from './review'

test('allSeen requires every field key seen', () => {
  const r = { done: false, items: { a: { seen: true, flag: null } } }
  expect(allSeen(r, ['a'])).toBe(true)
  expect(allSeen(r, ['a', 'b'])).toBe(false)
})

test('packetStatus derivation', () => {
  const clean = { matchedBy: 'cccd', review: { done: true, items: {} } } as any
  expect(packetStatus(clean)).toBe('clear')
  expect(packetStatus({ ...clean, review: { done: false, items: {} } })).toBe('untouched')
  expect(packetStatus({ ...clean, review: { done: false,
    items: { a: { seen: true, flag: null } } } })).toBe('in_review')
  expect(packetStatus({ ...clean, matchedBy: 'name' })).toBe('needs_resubmit')
})

test('calloutAnchor flips below when no room above', () => {
  const box = { left: 100, top: 5, width: 200, height: 30 }
  const a = calloutAnchor(box, 40, 800)        // calloutH=40, paneH=800
  expect(a.placement).toBe('below')
  const b = calloutAnchor({ ...box, top: 400 }, 40, 800)
  expect(b.placement).toBe('above')
})
