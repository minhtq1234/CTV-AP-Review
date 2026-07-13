import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Export build: bundle the whole app into ONE classic (non-module) IIFE script with
// the CSS in a single file, so scripts/build-single.mjs can inline everything into a
// single self-contained .html that opens straight from file:// (ES-module scripts and
// same-origin fetches are blocked under file://, hence iife + inlined data: assets).
export default defineConfig({
  plugins: [react()],
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    outDir: 'dist-single',
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    lib: {
      entry: 'src/main.tsx',
      name: 'APReview',
      formats: ['iife'],
      fileName: () => 'app.js',
    },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
})
