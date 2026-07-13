import type { CtvFolder } from './types'
import { assetUrl } from '../assets'

// Load a folder from a manifest.json file — the exact artifact the splitter emits
// (after the OCR pass fills each field's `sources`). Proves the splitter → reviewer seam.
// assetUrl() lets this resolve to an inlined data: URI in the single-file export.
export async function loadManifestFolder(url: string): Promise<CtvFolder> {
  const resolved = assetUrl(url)
  // Single-file export: the manifest is an inlined data: URI. Decode it directly (no
  // fetch) so the whole prototype runs from file:// with zero network dependency.
  if (resolved.startsWith('data:')) return JSON.parse(decodeDataUri(resolved)) as CtvFolder
  const res = await fetch(resolved)
  if (!res.ok) throw new Error(`manifest ${url}: HTTP ${res.status}`)
  return (await res.json()) as CtvFolder
}

// Decode a data: URI's body to a UTF-8 string (handles base64 + the Vietnamese text).
function decodeDataUri(uri: string): string {
  const comma = uri.indexOf(',')
  const meta = uri.slice(0, comma)
  const body = uri.slice(comma + 1)
  const bytes = meta.includes(';base64')
    ? Uint8Array.from(atob(body), c => c.charCodeAt(0))
    : new TextEncoder().encode(decodeURIComponent(body))
  return new TextDecoder('utf-8').decode(bytes)
}
