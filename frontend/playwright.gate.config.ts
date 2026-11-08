import { defineConfig, devices } from "@playwright/test";

const mode = process.env.GATE_MODE || "replay";
if (!["live", "record", "replay"].includes(mode)) throw new Error("GATE_MODE must be live, record or replay");
const apiPort = process.env.GATE_API_PORT || "8022";
const webPort = process.env.GATE_WEB_PORT || "5189";

export default defineConfig({
  testDir: "./gates",
  testMatch: "**/*.pw.ts",
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 90_000 },
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${process.env.E2E_PYTHON || "python"}" -m scripts.serve_app_gate ${mode} --port ${apiPort}`,
      cwd: "../backend", url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: false, timeout: 120_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      url: `http://127.0.0.1:${webPort}`, reuseExistingServer: false,
      env: { API_PORT: apiPort, WEB_PORT: webPort },
    },
  ],
});
