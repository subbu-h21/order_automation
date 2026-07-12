import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/fetch-order': 'http://127.0.0.1:8000',
      '/status': 'http://127.0.0.1:8000',
      '/branches': 'http://127.0.0.1:8000',
    },
  },
})
