import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      proxy: {
        '/api': env.KD_AGENT_API_ORIGIN || 'http://127.0.0.1:8000',
      },
    },
  }
})
