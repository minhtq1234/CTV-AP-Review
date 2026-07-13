import { describe, it, expect } from 'vitest'
import { loupeFrame, boxToViewport } from './loupe'

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
