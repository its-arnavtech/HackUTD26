import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Ports come from the repo-root .env (each agent folder sets its own).
// loadEnv here only reads API_PORT and WEB_PORT for the dev server config;
// nothing from .env is exposed to the browser bundle.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const apiPort = env.API_PORT || "8000";
  const webPort = Number(env.WEB_PORT || "5173");

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: webPort,
      strictPort: true,
      proxy: {
        "/api": `http://localhost:${apiPort}`,
      },
    },
  };
});
