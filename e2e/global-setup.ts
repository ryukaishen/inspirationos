import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { request } from "@playwright/test";

import { E2E_USER_EMAIL, E2E_USER_PASSWORD, STORAGE_STATE_PATH } from "./auth-constants";

// Synthetic fixture ZIPs are generated at test time by the same stdlib-only
// builder the backend tests use — nothing export-like is ever committed.
// The --unique marker gives each run distinct checksums so the dedupe flow
// stays testable against a long-lived dev stack.
const FIXTURES_DIR = path.resolve(__dirname, ".fixtures");

function runFixtureBuilder(): void {
  const script = path.resolve(__dirname, "..", "backend", "tests", "fixture_builder.py");
  const unique = String(Date.now());
  const candidates = process.platform === "win32" ? ["python", "python3"] : ["python3", "python"];
  let lastError: unknown = null;
  for (const python of candidates) {
    try {
      execFileSync(python, [script, "--out", FIXTURES_DIR, "--unique", unique], {
        stdio: "inherit",
      });
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(
    `could not run fixture_builder.py with any of [${candidates.join(", ")}]: ${String(lastError)}`,
  );
}

// Logs in once and saves the session cookie as Playwright storageState,
// reused by every spec via playwright.config.ts's `use.storageState` — one
// real login instead of one per spec file. The account itself is seeded by
// `python -m app.cli create-user` (CI workflow / Makefile `e2e` target)
// before this runs; a missing/wrong account fails loudly here rather than
// as a mysterious redirect-to-/login in every spec.
async function loginAndSaveStorageState(): Promise<void> {
  mkdirSync(path.dirname(STORAGE_STATE_PATH), { recursive: true });
  const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
  const context = await request.newContext({ baseURL });
  const response = await context.post("/api/auth/login", {
    headers: { "X-Requested-With": "XMLHttpRequest" },
    data: { email: E2E_USER_EMAIL, password: E2E_USER_PASSWORD },
  });
  if (!response.ok()) {
    throw new Error(
      `e2e login failed (${response.status()}) — did the create-user step run against this stack?`,
    );
  }
  await context.storageState({ path: STORAGE_STATE_PATH });
  await context.dispose();
}

export default async function globalSetup(): Promise<void> {
  mkdirSync(FIXTURES_DIR, { recursive: true });
  runFixtureBuilder();
  await loginAndSaveStorageState();
}
