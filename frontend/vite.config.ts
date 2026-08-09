import react from '@vitejs/plugin-react';
import path from 'node:path';
import { defineConfig } from 'vite';

// The dev server proxies /api to the backend so the browser sees a single
// origin. Production serves the built assets from nginx, which proxies the
// same prefix to the backend container.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
