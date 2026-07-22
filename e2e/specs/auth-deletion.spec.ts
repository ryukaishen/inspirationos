import path from "node:path";

import { expect, test } from "@playwright/test";

import { E2E_USER_EMAIL, E2E_USER_PASSWORD } from "../auth-constants";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

// Every other spec reuses the shared logged-in storageState (see
// playwright.config.ts); this file is the one place that needs to start
// logged out to exercise the login UI and the redirect guard itself.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("auth", () => {
  test("visiting a protected page while logged out redirects to /login", async ({ page }) => {
    await page.goto("/inbox");
    await expect(page).toHaveURL(/\/login/);
  });

  test("wrong credentials show an error and do not navigate away", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("login-email").fill(E2E_USER_EMAIL);
    await page.getByTestId("login-password").fill("definitely-not-the-password");
    await page.getByTestId("login-submit").click();

    await expect(page.getByTestId("login-error")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("correct credentials log in, and logout revokes access immediately", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("login-email").fill(E2E_USER_EMAIL);
    await page.getByTestId("login-password").fill(E2E_USER_PASSWORD);
    await page.getByTestId("login-submit").click();

    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("logout-button")).toBeVisible();

    await page.getByTestId("logout-button").click();
    await expect(page).toHaveURL(/\/login/);

    // The session is gone server-side too, not just the client-side redirect.
    await page.goto("/inbox");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("raw import deletion", () => {
  test("upload, then delete with typed confirmation removes it from the active list", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByTestId("login-email").fill(E2E_USER_EMAIL);
    await page.getByTestId("login-password").fill(E2E_USER_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL("/");

    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "variant_a.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });
    await expect(page.getByTestId("import-detail")).toContainText("variant_a.zip");
    const importId = page.url().match(/\/import\/(\d+)$/)?.[1];
    expect(importId).toBeTruthy();

    await page.getByTestId("import-delete-open").click();
    const confirmButton = page.getByTestId("import-delete-confirm");
    await expect(confirmButton).toBeDisabled();

    // The fixture builder's --unique marker varies content/checksum per run,
    // but the filename itself is always this literal string.
    await page.getByTestId("import-delete-confirm-input").fill("variant_a.zip");
    await expect(confirmButton).toBeEnabled();
    await confirmButton.click();

    await expect(page).toHaveURL("/import");
    const row = page
      .getByTestId("import-row")
      .filter({ has: page.locator(`a[href="/import/${importId}"]`) });
    await expect(row.getByTestId("import-row-status")).toHaveText("deleted");
  });
});
