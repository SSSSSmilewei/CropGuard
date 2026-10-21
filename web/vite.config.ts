import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物 web/dist 由 api_server.py 直接托管（比赛现场无外网、无 Node，dist 必须提交进仓库）。
// 开发时 `npm run dev`，接口与 WebSocket 代理到本机 8080 的 api_server。
const BACKEND = process.env.CG_BACKEND || 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': BACKEND,
      '/qr': BACKEND,
      '/docs': BACKEND,
      '/openapi.json': BACKEND,
      '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true },
    },
  },
})
