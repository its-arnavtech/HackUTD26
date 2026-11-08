import { generateKeyPairSync, randomBytes } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// L13: the app with AUTH_ENABLED=true, throwaway keys and a throwaway auth database.
// `npm run test:auth`. Passkeys need a real host name (not an IP), so this run uses localhost.
// The config is evaluated again in each worker; workers inherit the env set here, so keys match.
if (!process.env.E2E_AUTH_KEY) {
  const { privateKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  process.env.E2E_AUTH_KEY = Buffer.from(privateKey.export({ type: "pkcs8", format: "pem" }) as string).toString("base64");
  process.env.E2E_DATA_KEYS = `k1:${randomBytes(32).toString("base64")}`;
  process.env.E2E_AUTH_DB = join(mkdtempSync(join(tmpdir(), "sentinel-auth-")), "auth.sqlite");
}

const apiPort = process.env.E2E_AUTH_API_PORT || "8023";
const webPort = process.env.E2E_AUTH_WEB_PORT || "5190";

export const authEnv = {
  AUTH_ENABLED: "true",
  JWT_PRIVATE_KEY: process.env.E2E_AUTH_KEY!,
  DATA_ENCRYPTION_KEYS: process.env.E2E_DATA_KEYS!,
  AUTH_DB_PATH: process.env.E2E_AUTH_DB!,
  WEBAUTHN_RP_ID: "localhost",
  WEBAUTHN_ORIGINS: `http://localhost:${webPort}`,
};

export default defineConfig({
  testDir: "./e2e-auth",
  testMatch: "**/*.pw.ts",
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${webPort}`,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${process.env.E2E_PYTHON || "python"}" -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${apiPort}/api/health`,
      reuseExistingServer: false,
      env: { USE_MOCKS: "true", MOCK_ROUTES: "", LIVE_ROUTES: "", DEMO_MODE: "replay", GEMINI_API_KEY: "", ...authEnv },
    },
    {
      command: "npm run dev -- --host localhost",
      url: `http://localhost:${webPort}`,
      reuseExistingServer: false,
      env: { API_PORT: apiPort, WEB_PORT: webPort },
    },
  ],
});
