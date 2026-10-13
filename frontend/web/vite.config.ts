import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../../backend/mailbox-service/src/main/resources/static',
    emptyOutDir: true,
    sourcemap: false,
  },
})
