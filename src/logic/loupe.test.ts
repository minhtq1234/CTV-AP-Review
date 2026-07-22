import { describe, it, expect } from 'vitest'
import { loupeFrame, boxToViewport, inflateBbox } from './loupe'

const nat = { w: 800, h: 1120 }
const vp = { w: 500, h: 600 }

describe('loupeFrame', () => {
  it('with no box, fits the whole page centered at 0.92 scale', () => {
    const f = loupeFrame(null, nat, vp)
    const expected = Math.min(vp.w / nat.w, vp.h / nat.h) * 0.92
    expect(f.scale).toBeCloseTo(expected, 5)
    expect(f.tx).toBeCloseTo((vp.w - nat.w * f.scale) / 2, 5)
    expect(f.ty).toBeCloseTo((vp.h - nat.h * f.scale) / 2, 5)
  })
  it('centers a small box in the viewport', () => {
    const bbox = { x: 600, y: 900, width: 120, height: 28 }
    const f = loupeFrame(bbox, nat, vp)
    const cx = bbox.x + bbox.width / 2, cy = bbox.y + bbox.height / 2
    expect(f.tx + cx * f.scale).toBeCloseTo(vp.w / 2, 4)
    expect(f.ty + cy * f.scale).toBeCloseTo(vp.h / 2, 4)
  })
  it('clamps magnification to [1.1, 2.0]', () => {
    const tiny = { x: 10, y: 10, width: 4, height: 4 }
    expect(loupeFrame(tiny, nat, vp).scale).toBeLessThanOrEqual(2.0)
    const big = { x: 0, y: 0, width: 800, height: 1120 }
    expect(loupeFrame(big, nat, vp).scale).toBeLessThanOrEqual(Math.min(vp.w / 800, vp.h / 1120) * 0.92 + 1e-9)
  })
  it('returns identity for zero-size natural image', () => {
    expect(loupeFrame(null, { w: 0, h: 0 }, vp)).toEqual({ scale: 1, tx: 0, ty: 0 })
  })
})

describe('boxToViewport', () => {
  it('maps a natural-px box into viewport coords under a frame', () => {
    const r = boxToViewport({ x: 100, y: 50, width: 40, height: 20 }, { scale: 2, tx: 10, ty: 5 })
    expect(r).toEqual({ left: 210, top: 105, width: 80, height: 40 })
  })
})

describe('inflateBbox', () => {
  it('grows the box by frac on each side when clear of the page bounds', () => {
    const bbox = { x: 100, y: 100, width: 40, height: 20 }
    const r = inflateBbox(bbox, 0.2, 800, 1120)
    // dx = 40*0.2 = 8, dy = 20*0.2 = 4
    expect(r).toEqual({ x: 92, y: 96, width: 56, height: 28 })
  })

  it('clamps growth at the top-left page edge', () => {
    const bbox = { x: 0, y: 0, width: 40, height: 20 }
    const r = inflateBbox(bbox, 0.2, 800, 1120)
    // left/top can't go below 0; right/bottom still grow by dx/dy = 8/4
    expect(r).toEqual({ x: 0, y: 0, width: 48, height: 24 })
  })

  it('clamps growth at the bottom-right page edge', () => {
    const bbox = { x: 770, y: 1110, width: 30, height: 10 }
    const r = inflateBbox(bbox, 0.2, 800, 1120)
    // dx = 6, dy = 2 -> right/bottom would exceed page bounds, so clamp to 800/1120
    expect(r).toEqual({ x: 764, y: 1108, width: 36, height: 12 })
  })

  it('never produces a negative-size box for a bbox that fills the whole page', () => {
    const bbox = { x: 0, y: 0, width: 800, height: 1120 }
    const r = inflateBbox(bbox, 0.2, 800, 1120)
    expect(r).toEqual({ x: 0, y: 0, width: 800, height: 1120 })
  })
})
