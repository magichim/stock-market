import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: {
    // 종목 로고는 작아도 JS에 인라인하지 않고 파일로 낸다
    assetsInlineLimit: (file) => (file.includes('/assets/stock-logo/') ? false : undefined),
    rollupOptions: {
      output: {
        // 종목 로고는 해시 없이 /assets/stock-logo/{symbol}.svg로 — 소스와 같은 경로로 접근된다
        assetFileNames: (asset) =>
          asset.originalFileNames?.some((f) => f.includes('assets/stock-logo/'))
            ? 'assets/stock-logo/[name][extname]'
            : 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    // predict-market(5173·8000)과 겹치지 않는 포트. 로컬은 localhost로 접속해야 predict-market 쿠키가 공유된다
    port: 5273,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8100',
    },
  },
})
