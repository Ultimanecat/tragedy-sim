import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  fullyParallel: true,
  // Several full legal-action walks are CPU-heavy and share one local Python
  // service. Three workers avoid transient fetch failures on Windows hosts.
  workers: 3,
  use: { baseURL: "http://127.0.0.1:8877", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
