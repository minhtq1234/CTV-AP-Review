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
  const targetH = vp.h * 0.14
  const magnify = clamp(targetH / bbox.height, 1.1, 2.5)
  const fit = Math.min(vp.w / bbox.width, vp.h / bbox.height) * 0.92
  const s = Math.min(magnify, fit)
  const cx = bbox.x + bbox.width / 2
  const cy = bbox.y + bbox.height / 2
  return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
}

export function boxToViewport(bbox: Bbox, frame: Frame) {
  return {
    left: frame.tx + bbox.x * frame.scale,
    top: frame.ty + bbox.y * frame.scale,
    width: bbox.width * frame.scale,
    height: bbox.height * frame.scale,
  }
}
