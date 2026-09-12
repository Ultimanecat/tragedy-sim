import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  fullyParallel: true,
  // Full legal-action walks share one local Python service. Serial execution is
  // deliberate: Windows can exhaust transient socket buffers (WSAENOBUFS) when
  // two long simulations create and discard thousands of HTTP connections.
  workers: 1,
  use: { baseURL: "http://127.0.0.1:8877", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
