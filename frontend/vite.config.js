import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/output': 'http://127.0.0.1:8000',
      '/upload': 'http://127.0.0.1:8000',
    },
  },
  base: './',
})
