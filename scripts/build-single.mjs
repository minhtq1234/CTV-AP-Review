// Inline the export build (dist-single/) + every public asset into ONE self-contained
// .html that runs from file://. Run after `vite build --config vite.config.export.ts`.
import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, extname, sep } from 'node:path'

const root = process.cwd()
const distDir = join(root, 'dist-single')
const publicDir = join(root, 'public')
const outFile = join(root, 'AP-Review-Prototype.html')

// 1. Built JS (single IIFE) + CSS (single file, cssCodeSplit:false).
const distFiles = readdirSync(distDir)
const jsName = distFiles.find(f => f.endsWith('.js'))
if (!jsName) throw new Error('no .js in dist-single — did the export build run?')
const js = readFileSync(join(distDir, jsName), 'utf8')
const css = distFiles.filter(f => f.endsWith('.css'))
  .map(f => readFileSync(join(distDir, f), 'utf8')).join('\n')

// 2. Every file under public/ → a data: URI, keyed by its served path ("/flights/...svg").
const MIME = { '.svg': 'image/svg+xml', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg' }
const assets = {}
const walk = dir => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) { walk(p); continue }
    const key = '/' + relative(publicDir, p).split(sep).join('/')
    const mime = MIME[extname(p).toLowerCase()] || 'application/octet-stream'
    assets[key] = `data:${mime};base64,${readFileSync(p).toString('base64')}`
  }
}
walk(publicDir)

// 3. Assemble. Guard any literal </script>/</style> so inlined code can't close its tag.
const guard = s => s.replace(/<\/(script|style)/gi, '<\\/$1')
const html = `<!doctype html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Duyệt đề nghị thanh toán — AP Review</title>
<style>${guard(css)}</style>
</head>
<body>
<div id="root"></div>
<script>window.__ASSETS__=${guard(JSON.stringify(assets))}</script>
<script>${guard(js)}</script>
</body>
</html>
`
writeFileSync(outFile, html)
const mb = (Buffer.byteLength(html) / 1024 / 1024).toFixed(2)
console.log(`Wrote ${relative(root, outFile)} — ${mb} MB, ${Object.keys(assets).length} inlined assets`)
