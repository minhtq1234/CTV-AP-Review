import type { CtvFolder } from './types'

// Load a folder from a manifest.json file — the exact artifact the splitter emits
// (after the OCR pass fills each field's `sources`). Proves the splitter → reviewer seam.
export async function loadManifestFolder(url: string): Promise<CtvFolder> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`manifest ${url}: HTTP ${res.status}`)
  return (await res.json()) as CtvFolder
}
