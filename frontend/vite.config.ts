import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    host: '127.0.0.1',
    strictPort: true,
    proxy: {
      '^/api/': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false,
        configure: (proxy) => {
          proxy.on('proxyReq', (_proxyReq, req) => {
            (req as any).__t = Date.now();
            console.log(`[proxy] --> ${req.method} ${req.url}`);
          });
          proxy.on('proxyRes', (_proxyRes, req) => {
            console.log(`[proxy] <-- ${req.url} (${Date.now() - (req as any).__t}ms)`);
          });
        },
      },
    },
  },
})