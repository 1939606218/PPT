import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:18766',
        changeOrigin: true,
        timeout: 0,       // 不超时（analyze 需要几分钟）
        proxyTimeout: 0,  // proxy 侧也不超时
      },
    },
  },
  build: { outDir: 'dist' },
})
