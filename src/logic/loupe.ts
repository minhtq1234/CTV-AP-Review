import type { Bbox, Frame } from '../types'

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export function loupeFrame(
  bbox: Bbox | null,
  nat: { w: number; h: number },
  vp: { w: number; h: number },
): Frame {
  if (nat.w === 0 || nat.h === 0) return { scale: 1, tx: 0, ty: 0 }
  if (!bbox) {
    const s = Math.min(vp.w / nat.w, vp.h / nat.h) * 0.92
    return { scale: s, tx: (vp.w - nat.w * s) / 2, ty: (vp.h - nat.h * s) / 2 }
  }
  // Aim for the box to fill ~10% of viewport height so surrounding content stays visible,
  // clamped to [1.1x, 2.0x]. Lower the 0.10 / 2.0 to zoom out further.
  const targetH = vp.h * 0.10
  const magnify = clamp(targetH / bbox.height, 1.1, 2.0)
  const fit = Math.min(vp.w / bbox.width, vp.h / bbox.height) * 0.92
  const s = Math.min(magnify, fit)
  const cx = bbox.x + bbox.width / 2
  const cy = bbox.y + bbox.height / 2
  return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
}

// Grow a bbox by `frac` of its own width/height on each side (e.g. 0.2 = 20% larger all
// round), clamped to the page's natural bounds so the box never runs off the page.
export function inflateBbox(bbox: Bbox, frac: number, natW: number, natH: number): Bbox {
  const dx = bbox.width * frac
  const dy = bbox.height * frac
  const left = clamp(bbox.x - dx, 0, natW)
  const top = clamp(bbox.y - dy, 0, natH)
  const right = clamp(bbox.x + bbox.width + dx, 0, natW)
  const bottom = clamp(bbox.y + bbox.height + dy, 0, natH)
  return { x: left, y: top, width: right - left, height: bottom - top }
}

export function boxToViewport(bbox: Bbox, frame: Frame) {
  return {
    left: frame.tx + bbox.x * frame.scale,
    top: frame.ty + bbox.y * frame.scale,
    width: bbox.width * frame.scale,
    height: bbox.height * frame.scale,
  }
}
