import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

test.describe("consent-gated enrichment and fast keyboard review", () => {
  test.describe.configure({ mode: "serial" });

  test("upload, extract, enable enrichment, and drive the review loop by keyboard only", async ({
    page,
    context,
  }) => {
    // --- upload + scan ---------------------------------------------------
    // rich_b.zip (not rich_a.zip): inbox.spec.ts already uploads rich_a.zip,
    // and spec files run in parallel against the same shared dev-stack DB —
    // identical logical content, different layout/checksum, so no collision.
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "rich_b.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });

    // --- select the friend conversation (not the self-DM) and extract ----
    await page.getByRole("link", { name: "Select conversations →" }).click();
    await expect(page).toHaveURL(/\/import\/\d+\/conversations$/);
    const friendRow = page
      .getByTestId("conversation-row")
      .filter({ hasNot: page.getByTestId("self-dm-badge") });
    await friendRow.locator('input[type="checkbox"]').check();
    await page.getByTestId("extract-button").click();
    await expect(page.getByTestId("extract-job-status")).toContainText("succeeded", {
      timeout: 20_000,
    });

    // --- consent gate: the toggle alone does nothing without confirming --
    // This dev-stack DB is long-lived across runs (see inbox.spec.ts's own
    // note on this), so enrichment may already be enabled from a prior run;
    // force the disabled baseline first so this always exercises the
    // enable+consent-dialog path fresh, not an accidental disable.
    await page.goto("/settings");
    const toggle = page.getByTestId("enrichment-toggle");
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute("aria-checked")) === "true") {
      await toggle.click(); // disabling never shows the dialog
      await expect(toggle).toHaveAttribute("aria-checked", "false");
    }
    await toggle.click();
    await expect(page.getByText("Enable metadata enrichment?")).toBeVisible();
    await page.getByTestId("consent-confirm").click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("consent-timestamp")).toBeVisible();

    // --- fast review: every action below is a keyboard press, no mouse ---
    await page.goto("/review");
    await expect(page.getByTestId("review-card")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("review-progress")).toHaveText(/^1 of \d+$/);

    // j/k pure navigation: advances and returns without changing anything.
    await page.keyboard.press("j");
    await expect(page.getByTestId("review-progress")).toHaveText(/^2 of \d+$/);
    await page.keyboard.press("k");
    await expect(page.getByTestId("review-progress")).toHaveText(/^1 of \d+$/);

    // o opens the original reel in a new tab.
    const originalUrl = await page.getByTestId("open-original").getAttribute("href");
    const [popup] = await Promise.all([context.waitForEvent("page"), page.keyboard.press("o")]);
    expect(popup.url()).toBe(originalUrl);
    await popup.close();

    // e focuses the note field; typing then Enter saves a one-sentence
    // note, sets status to reviewed, and advances — no click anywhere.
    const distinctiveNote = `distinctive review note ${Date.now()}`;
    await page.keyboard.press("e");
    await expect(page.getByTestId("review-note")).toBeFocused();
    await page.keyboard.type(distinctiveNote);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("review-progress")).toHaveText(/^2 of \d+$/);

    // s skips the next item without saving; 1-5 sets a status directly.
    await page.keyboard.press("s");
    await expect(page.getByTestId("review-progress")).toHaveText(/^3 of \d+$/);
    await page.keyboard.press("4"); // archived, per ITEM_STATUSES order
    await expect(page.getByTestId("review-progress")).toHaveText(/^4 of \d+$/);

    // --- verify the Enter save+advance actually persisted, through the
    // inbox (not just the review page's own optimistic state) -------------
    await page.goto("/inbox");
    await page.getByTestId("search-input").fill(distinctiveNote);
    await expect(page.getByTestId("item-card")).toHaveCount(1);
    await expect(page.getByTestId("item-status")).toHaveText("Reviewed");
  });
});
