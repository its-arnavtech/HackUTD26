import { defineConfig, devices } from "@playwright/test";

const apiPort = process.env.E2E_API_PORT || "8021";
const webPort = process.env.E2E_WEB_PORT || "5188";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.pw.ts",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${process.env.E2E_PYTHON || "python"}" -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: false,
      env: { USE_MOCKS: "true", MOCK_ROUTES: "", LIVE_ROUTES: "", DEMO_MODE: "replay", GEMINI_API_KEY: "" },
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
      env: { API_PORT: apiPort, WEB_PORT: webPort },
    },
  ],
});
