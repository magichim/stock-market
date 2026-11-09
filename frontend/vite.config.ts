import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // predict-market(5173·8000)과 겹치지 않는 포트. 로컬은 localhost로 접속해야 predict-market 쿠키가 공유된다
    port: 5273,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8100',
    },
  },
})
