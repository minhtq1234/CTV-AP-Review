// Resolve a public asset path (e.g. "/flights/x/eform.svg") to a loadable URL.
//
// In the normal dev/served build this is a no-op — the path is returned as-is and
// the browser fetches it from the server. In the single-file export build, the
// inliner injects `window.__ASSETS__` mapping every public path to a data: URI, so
// the whole prototype runs from a single file:// document with no server.
export function assetUrl(path: string): string {
  const map = (globalThis as { __ASSETS__?: Record<string, string> }).__ASSETS__
  return (map && map[path]) || path
}
