import { defineConfig, devices } from "@playwright/test";

// Runs against the full compose stack (docker compose up -d --build):
// frontend on :3000 proxying /api/* to the backend, worker consuming queues.
export default defineConfig({
  testDir: "./specs",
  globalSetup: "./global-setup.ts",
  fullyParallel: false,
  // One worker: every spec file drives the same shared compose stack and
  // database, and parallel fresh-profile browsers contend for the dev
  // server's cold asset chunks (observed as page.goto load timeouts once the
  // suite grew to five files). Serial is deterministic and fast enough.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
