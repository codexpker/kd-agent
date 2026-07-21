import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const virtualEnvironmentPython = resolve(
  repositoryRoot,
  process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python',
)
const python = process.env.KD_AGENT_PYTHON
  || (existsSync(virtualEnvironmentPython) ? virtualEnvironmentPython : 'python')
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'real-infrastructure.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: '../tmp/playwright-real-infra-results',
  reporter: [['line']],
  use: {
    baseURL: 'http://127.0.0.1:5175',
    browserName: 'chromium',
    viewport: { width: 1280, height: 720 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --app-dir "${resolve(repositoryRoot, 'backend')}" --host 127.0.0.1 --port 8011`,
      url: 'http://127.0.0.1:8011/api/v1/healthz',
      timeout: 30_000,
      reuseExistingServer: false,
      env: {
        RESEARCH_GATEWAY_MODE: 'local',
        RETRIEVAL_BACKEND: 'demo',
        DOCUMENT_STRUCTURE_BACKEND: 'mysql',
        EVIDENCE_GRAPH_BACKEND: 'neo4j',
        PRIVATE_PDF_PREVIEW_ENABLED: 'true',
        ASSISTANT_BACKEND: 'offline',
        PROJECT_CLAIM_BACKEND: 'memory',
        EXPERIMENT_RUN_BACKEND: 'memory',
        CORS_ORIGINS: 'http://127.0.0.1:5175',
      },
    },
    {
      command: `${npm} run dev -- --host 127.0.0.1 --port 5175`,
      url: 'http://127.0.0.1:5175',
      timeout: 30_000,
      reuseExistingServer: false,
      env: {
        KD_AGENT_API_ORIGIN: 'http://127.0.0.1:8011',
      },
    },
  ],
})
