import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

// Serial: the duplicate test re-uploads the ZIP that the first test uploaded.
test.describe("secure import", () => {
  test.describe.configure({ mode: "serial" });

  test("valid export upload reaches scanned with stub counts", async ({ page }) => {
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "variant_a.zip"));
    await page.getByRole("button", { name: "Upload" }).click();

    // successful upload navigates to the detail page, which polls every 2s
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });
    await expect(page.getByTestId("import-counts")).toHaveText("2 entries · 1 message files");
    await expect(page.getByTestId("scan-job-status")).toContainText("succeeded");
  });

  test("re-uploading the same ZIP reports a duplicate with a link", async ({ page }) => {
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "variant_a.zip"));
    await page.getByRole("button", { name: "Upload" }).click();

    const error = page.getByTestId("upload-error");
    await expect(error).toContainText("already uploaded");
    await expect(error.getByRole("link", { name: "View the existing import" })).toBeVisible();
  });

  test("HTML export is rejected with the re-request-as-JSON message", async ({ page }) => {
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "html_export.zip"));
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByTestId("upload-error")).toContainText(
      "Re-request your Instagram data export in JSON format",
    );
  });
});
