import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
const python =
  process.env.RECALLNEST_TEST_PYTHON ||
  resolve(
    "..",
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
export default defineConfig({
  testDir: "./e2e",
  globalTeardown: "./e2e/teardown.ts",
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
  webServer: [
    {
      command: `"${python}" ../tests/e2e_server.py`,
      url: "http://127.0.0.1:18787/api/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      env: { RECALLNEST_API_URL: "http://127.0.0.1:18787" },
      reuseExistingServer: false,
    },
  ],
});
