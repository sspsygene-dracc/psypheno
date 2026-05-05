import { defineConfig, devices } from "@playwright/test";

// E2E tests assume a Next.js dev server is already running on
// `baseURL` (default: http://localhost:3000). The repo's CLAUDE.md
// notes the user often has :3000 running already, and Next 16 / Turbopack
// only allows one dev server per checkout — so we deliberately do NOT
// launch one from here. Set E2E_BASE_URL to point at a different host
// or port (e.g. a worktree's :3010 instance).
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
