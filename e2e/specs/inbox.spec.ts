import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

test.describe("inspiration inbox", () => {
  test.describe.configure({ mode: "serial" });

  test("upload, select conversation, extract, and browse the inbox", async ({ page }) => {
    // --- upload + scan ---------------------------------------------------
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "rich_a.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });

    // --- conversation selector: self-DM stays unchecked, friend selected --
    await page.getByRole("link", { name: "Select conversations →" }).click();
    await expect(page).toHaveURL(/\/import\/\d+\/conversations$/);
    const conversationsUrl = page.url();

    const rows = page.getByTestId("conversation-row");
    await expect(rows).toHaveCount(2);

    // Filtered by badge presence, not text: the friend row's participant
    // list also contains the substring "Synthetic Owner" (the owner is a
    // participant in every thread), so a text-based filter would match both.
    const selfRow = rows.filter({ has: page.getByTestId("self-dm-badge") });
    await expect(selfRow.getByTestId("self-dm-badge")).toContainText("Self-DM candidate");
    await expect(selfRow.locator('input[type="checkbox"]')).not.toBeChecked();

    const friendRow = rows.filter({ hasNot: page.getByTestId("self-dm-badge") });
    const friendCheckbox = friendRow.locator('input[type="checkbox"]');
    const friendCheckboxId = await friendCheckbox.getAttribute("id"); // "conversation-<id>"
    const friendConversationId = friendCheckboxId?.replace("conversation-", "");
    await friendCheckbox.check();

    await page.getByTestId("extract-button").click();
    await expect(page.getByTestId("extract-job-status")).toContainText("succeeded", {
      timeout: 20_000,
    });

    // --- inbox: duplicate group collapses to one card of 3 ---------------
    await page.getByRole("link", { name: "Go to inbox →" }).click();
    await expect(page).toHaveURL(/\/inbox$/);

    // This dev-stack database persists across manual-verification sessions
    // and may already hold unrelated items, so scope to just the freshly
    // extracted conversation (mirrors the marker-scoping used in the backend
    // integration tests for the same reason).
    await page.getByTestId("conversation-filter").selectOption(friendConversationId!);

    const cards = page.getByTestId("item-card");
    await expect(cards).toHaveCount(3);

    const groupedCard = cards.filter({ has: page.getByTestId("duplicate-badge") });
    await expect(groupedCard).toHaveCount(1);
    await expect(groupedCard.getByTestId("duplicate-badge")).toHaveText("×3");

    // --- search narrows to exactly the item with that adjacent text ------
    await page.getByTestId("search-input").fill("More context after");
    await expect(page.getByTestId("item-card")).toHaveCount(1);

    await page.getByTestId("search-input").fill("");
    await expect(page.getByTestId("item-card")).toHaveCount(3);

    // --- a type filter narrows the result count ---------------------------
    // .click() rather than .check()/.uncheck(): the checkbox is controlled by
    // URL state via an async router.replace, so the native checked property
    // and the auto-waiting toHaveCount assertion settle a beat after the
    // click — .check()'s own post-click "did it flip" assertion is stricter
    // than that and fires before the re-render lands.
    const externalTypeCheckbox = page.getByRole("checkbox", { name: "External" });
    await externalTypeCheckbox.click();
    await expect(page.getByTestId("item-card")).toHaveCount(1);
    await externalTypeCheckbox.click();
    await expect(page.getByTestId("item-card")).toHaveCount(3);

    // --- bulk status change persists across a reload ----------------------
    const firstCard = page.getByTestId("item-card").nth(0);
    const secondCard = page.getByTestId("item-card").nth(1);
    const firstId = await firstCard.getAttribute("data-item-id");
    const secondId = await secondCard.getAttribute("data-item-id");
    await firstCard.getByRole("checkbox", { name: /Select item/ }).check();
    await secondCard.getByRole("checkbox", { name: /Select item/ }).check();

    await expect(page.getByTestId("bulk-selection-count")).toHaveText("2 selected");
    await page.getByTestId("bulk-apply-status").click(); // bulk toolbar defaults to "reviewed"
    await expect(page.getByTestId("bulk-toolbar")).toHaveCount(0); // selection clears on success

    await page.reload();
    for (const itemId of [firstId, secondId]) {
      const persistedCard = page.locator(`[data-testid="item-card"][data-item-id="${itemId}"]`);
      await expect(persistedCard.getByTestId("item-status")).toHaveText("Reviewed");
    }

    // --- accessibility smoke: zero critical violations --------------------
    const inboxViolations = (await new AxeBuilder({ page }).analyze()).violations.filter(
      (violation) => violation.impact === "critical",
    );
    expect(inboxViolations).toEqual([]);

    await page.goto(conversationsUrl);
    const selectorViolations = (await new AxeBuilder({ page }).analyze()).violations.filter(
      (violation) => violation.impact === "critical",
    );
    expect(selectorViolations).toEqual([]);
  });
});
