import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    proxy: {
      '/api': {
        // Override with SIFRA_API_PROXY=http://host:port when the API is elsewhere
        target: process.env.SIFRA_API_PROXY || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  // Tailwind v4 runs through @tailwindcss/vite. An empty PostCSS config stops Vite from
  // picking up a postcss.config.js from a parent directory (e.g. a global Tailwind v3 setup).
  css: {
    postcss: { plugins: [] },
  },
  build: {
    chunkSizeWarningLimit: 600,
  },
})
