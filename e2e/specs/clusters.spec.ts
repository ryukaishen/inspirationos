import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

// The analysis pipeline (embed -> cluster -> topics) runs offline with
// AI_PROVIDER=mock. The embedding provider may be the deterministic mock (CI)
// or real local fastembed (dev stacks) — assertions are provider-agnostic, so
// exact memberships live in the backend integration tests, not here. The
// first local-fastembed run downloads the embedding model once, hence the
// generous analysis timeout.
const ANALYSIS_TIMEOUT_MS = 240_000;

test.describe("semantic clusters", () => {
  test.describe.configure({ mode: "serial" });

  test("upload, extract, run analysis, edit a cluster, and bulk-describe it", async ({
    page,
  }) => {
    test.setTimeout(ANALYSIS_TIMEOUT_MS + 120_000);

    // --- upload + scan (own zip: other specs upload the rich fixtures) ----
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "clusters.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });

    // --- select the single conversation and extract -----------------------
    await page.getByRole("link", { name: "Select conversations →" }).click();
    const row = page
      .getByTestId("conversation-row")
      .filter({ hasText: "Synthetic Clusters" });
    await row.locator('input[type="checkbox"]').check();
    await page.getByTestId("extract-button").click();
    await expect(page.getByTestId("extract-job-status")).toContainText("succeeded", {
      timeout: 20_000,
    });

    // --- run the full analysis pipeline offline ---------------------------
    await page.goto("/clusters");
    await page.getByTestId("run-analysis").click();
    await expect(page.getByTestId("analysis-done")).toBeVisible({
      timeout: ANALYSIS_TIMEOUT_MS,
    });

    // At least one multi-item cluster with an AI-generated (mock) label.
    const cards = page.getByTestId("cluster-card");
    await expect(cards.first()).toBeVisible();
    await expect(cards.first().getByTestId("cluster-label")).not.toHaveText("");

    // --- edit the description; persists across a reload -------------------
    const uniqueDescription = `distinctive cluster description ${Date.now()}`;
    const firstCard = cards.first();
    await firstCard.getByTestId("cluster-edit").click();
    await firstCard.getByTestId("cluster-description-input").fill(uniqueDescription);
    await firstCard.getByTestId("cluster-save").click();
    await expect(firstCard.getByTestId("cluster-description")).toHaveText(uniqueDescription);
    await page.reload();
    await expect(
      page.getByTestId("cluster-card").first().getByTestId("cluster-description"),
    ).toHaveText(uniqueDescription, { timeout: 20_000 });

    // --- bulk-describe every member of the cluster ------------------------
    const reloadedCard = page.getByTestId("cluster-card").first();
    await reloadedCard.getByTestId("cluster-expand").click();
    await expect(reloadedCard.getByTestId("cluster-member").first()).toBeVisible({
      timeout: 20_000,
    });
    const uniqueNote = `distinctive cluster note ${Date.now()}`;
    await reloadedCard.getByTestId("bulk-note-input").fill(uniqueNote);
    await reloadedCard.getByTestId("bulk-apply").click();
    await expect(reloadedCard.getByTestId("cluster-action-status")).toContainText(
      "Note applied",
    );

    // Per-cluster Enrich action is wired (never clicked — e2e must make no
    // outbound requests; the consent gate itself is covered by review.spec).
    await expect(reloadedCard.getByTestId("cluster-enrich")).toBeVisible();

    // --- the bulk note is real item data, findable via inbox search -------
    await page.goto("/inbox");
    await page.getByTestId("search-input").fill(uniqueNote);
    await expect(page.getByTestId("item-card").first()).toBeVisible({ timeout: 20_000 });
  });
});
