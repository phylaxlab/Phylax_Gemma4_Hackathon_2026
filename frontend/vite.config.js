import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5173,
    allowedHosts: ['.trycloudflare.com', 'phylax-cam.com', 'www.phylax-cam.com'],
    headers: {
      'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
      Pragma: 'no-cache',
      Expires: '0',
    },
    proxy: {
      // Proxy API and WebSocket requests to the FastAPI backend
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
      '/thumbnails': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/frames': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
