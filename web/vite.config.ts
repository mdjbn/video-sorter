import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时 /api 代理到本地 FastAPI；构建产物由后端同端口托管，所以 base 用 '/'
export default defineConfig({
  base: '/',
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true } },
  },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1200 },
})
