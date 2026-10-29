import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  base: mode === 'production' ? '/static/' : '/',
  plugins: [react()],
  server: { port: 5175, strictPort: true },
  preview: { port: 5175, strictPort: true },
  test: {
    environment: 'happy-dom',
    setupFiles: './src/test/setup.js',
    restoreMocks: true,
  },
}))
