import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: ['factory-louis-relating-website.trycloudflare.com'],
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/output': 'http://127.0.0.1:8000',
      '/upload': 'http://127.0.0.1:8000',
    },
  },
})
