import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:15174",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: [
    {
      command:
        "FLOW_DB_PATH=/tmp/world-simulation-2d-e2e-$(date +%s%N).sqlite3 ../.venv/bin/uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 18123",
      url: "http://127.0.0.1:18123/api/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "VITE_PORT=15174 VITE_API_TARGET=http://127.0.0.1:18123 npm run dev -- --force",
      url: "http://127.0.0.1:15174",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
