import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: ['factory-louis-relating-website.trycloudflare.com'],
    port: 3002,
    // Fail loudly on a port clash instead of silently moving to the next free
    // port: a dev server that quietly relocates leaves the browser pointing at
    // a stale tab and the proxy config apparently broken.
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/output': 'http://127.0.0.1:8000',
      '/upload': 'http://127.0.0.1:8000',
    },
  },
})
