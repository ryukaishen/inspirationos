import path from "node:path";

// Test-only credential for the hermetic e2e stack — seeded by
// `docker compose exec backend python -m app.cli create-user` (CI workflow /
// Makefile `e2e` target) before Playwright starts. Not a real secret; only
// ever valid against a throwaway compose stack.
export const E2E_USER_EMAIL = "e2e@example.com";
export const E2E_USER_PASSWORD = "e2e-test-password-not-a-secret";

export const STORAGE_STATE_PATH = path.resolve(__dirname, ".auth", "session.json");
