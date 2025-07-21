import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@ee": path.resolve(__dirname, loadEnv(mode, process.cwd(), '').EE_COMPONENTS_PATH || "./nonexistent"),
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
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          ui: ['@radix-ui/react-dialog', '@radix-ui/react-dropdown-menu']
        }
      }
    }
  }
}))
