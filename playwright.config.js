import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 15000,
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['junit', { outputFile: 'artifacts/playwright.xml' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: 'uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8765 --no-access-log',
    url: 'http://127.0.0.1:8765/healthz',
    reuseExistingServer: false,
    timeout: 20000,
    stdout: 'pipe',
    stderr: 'pipe',
    gracefulShutdown: { signal: 'SIGTERM', timeout: 3000 },
    env: {
      AZURE_TENANT_ID: '',
      GRAPH_CLIENT_ID: '',
      GRAPH_AUTH_MODE: 'delegated',
      GRAPH_APPLICATION_CREDENTIALS_FILE: '',
      FOUNDRY_PROJECT_ENDPOINT: '',
      VOICELIVE_ENDPOINT: '',
      SHAREPOINT_INPUT_FOLDER_URL: '',
      SHAREPOINT_OUTPUT_FOLDER_URL: '',
      SHAREPOINT_INPUT_DRIVE_ID: '',
      SHAREPOINT_INPUT_FOLDER_ID: '',
      SHAREPOINT_OUTPUT_DRIVE_ID: '',
      SHAREPOINT_OUTPUT_FOLDER_ID: '',
    },
  },
});