import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  fullyParallel: true,
  workers: 4,
  use: { baseURL: "http://127.0.0.1:8877", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
