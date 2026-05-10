import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      '@':            resolve(__dirname, 'src'),
      '@lib':         resolve(__dirname, 'src/lib'),
      '@hooks':       resolve(__dirname, 'src/hooks'),
      '@store':       resolve(__dirname, 'src/store'),
      '@components':  resolve(__dirname, 'src/components'),
      '@modules':     resolve(__dirname, 'src/modules'),
    },
  },

  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },

  build: {
    target: 'es2022',
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-ui':    ['lucide-react', 'axios', 'zustand'],
        },
      },
    },
  },
})