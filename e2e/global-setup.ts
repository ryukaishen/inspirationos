import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

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

export default function globalSetup(): void {
  mkdirSync(FIXTURES_DIR, { recursive: true });
  runFixtureBuilder();
}
