import { defineConfig } from 'vite';

const serverPort = Number(process.env.REALM_PORT ?? 4777);

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/ws': { target: `ws://127.0.0.1:${serverPort}`, ws: true },
      '/api': { target: `http://127.0.0.1:${serverPort}` },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      input: {
        main: 'index.html',
        worldPreview: 'world-preview.html',
      },
    },
  },
});
