import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

// verification.zip (fixture_builder.build_verification_export_zip, M10)
// exercises every scan-pass skip category once, the message_requests/
// filtered_threads categories, an unrecognized category, and one
// same-shortcode duplicate pair — see backend/tests/fixture_builder.py's
// VERIFICATION_* constants for the exact expected numbers asserted below.
test.describe("import verification report", () => {
  test("scan surfaces every skip category; extract adds the duplicate summary", async ({
    page,
  }) => {
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "verification.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    const importUrl = page.url();
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });

    // --- verification report appears after scan, before extract -----------
    await expect(page.getByTestId("verification-report-card")).toBeVisible();
    await expect(page.getByTestId("verification-raw-entries")).toHaveText("6");
    await expect(page.getByTestId("verification-matched-entries")).toHaveText("5");
    await expect(page.getByTestId("verification-conversations")).toHaveText("4");
    await expect(page.getByTestId("verification-messages-parsed")).toHaveText("6");
    await expect(page.getByTestId("verification-messages-skipped")).toHaveText("3");
    await expect(page.getByTestId("verification-skip-non_dict_page_payload")).toContainText("1");
    await expect(page.getByTestId("verification-skip-message_not_object")).toContainText("1");
    await expect(
      page.getByTestId("verification-skip-message_missing_sender_or_timestamp"),
    ).toContainText("2");
    await expect(page.getByTestId("verification-skip-unrecognized_message_path")).toContainText(
      "1",
    );
    await expect(
      page.getByTestId("verification-skip-unrecognized_message_path_categories_seen"),
    ).toContainText("synthetic_unknown_category");
    // nothing extracted yet — those rows aren't rendered at all
    await expect(page.getByTestId("verification-extracted-messages")).toHaveCount(0);

    // --- select every conversation and extract -----------------------------
    await page.getByRole("link", { name: "Select conversations →" }).click();
    const checkboxes = page.getByTestId("conversation-row").locator('input[type="checkbox"]');
    await expect(checkboxes).toHaveCount(4);
    const count = await checkboxes.count();
    for (let i = 0; i < count; i += 1) {
      await checkboxes.nth(i).check();
    }
    await page.getByTestId("extract-button").click();
    await expect(page.getByTestId("extract-job-status")).toContainText("succeeded", {
      timeout: 20_000,
    });

    // --- back on the import detail page, the report now includes extracted
    // counts and the duplicate-reason summary -------------------------------
    await page.goto(importUrl);
    await expect(page.getByTestId("verification-extracted-messages")).toHaveText("6");
    await expect(page.getByTestId("verification-items-extracted")).toHaveText("2");
    const duplicateRow = page.getByTestId("verification-duplicate-same_shortcode");
    await expect(duplicateRow).toContainText("1 group");
    await expect(duplicateRow).toContainText("2 items");
  });
});
