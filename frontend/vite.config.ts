import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8088',
      '/v1': 'http://localhost:8088',
    },
  },
  build: {
    outDir: 'dist',
  },
})
