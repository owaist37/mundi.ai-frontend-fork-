import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // Base path to ensure assets are loaded correctly
  base: '/',
  // Configure Vite's dev server for proxying API requests to the backend during development
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/supertokens': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/drift': {
        target: 'http://localhost:8000',
        ws: true,
        rewriteWsOrigin: true,
      },
      '/room': {
        target: 'http://localhost:8000',
        ws: true,
        rewriteWsOrigin: true,
      }
    }
  },
  build: {
    sourcemap: mode === 'development',
    // Reduce memory usage during build
    chunkSizeWarningLimit: 1000,
  }
}))
