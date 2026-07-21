import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

// Analysis runs offline (AI_PROVIDER=mock; embedding provider mock in CI or
// local fastembed on dev stacks — first run downloads the model once).
const ANALYSIS_TIMEOUT_MS = 240_000;
const JOB_TIMEOUT_MS = 60_000;

// The dev-stack DB is long-lived, so every assertion is an increment or is
// scoped to a per-run unique marker — never an absolute count.
test.describe("project workspace", () => {
  test.describe.configure({ mode: "serial" });

  test("generate, re-rank, compare, combine, advise, and track milestones", async ({
    page,
  }) => {
    test.setTimeout(ANALYSIS_TIMEOUT_MS + 240_000);
    const marker = `${Date.now()}`;

    // --- upload + scan (own zip: checksum-distinct from clusters.spec) ----
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "projects.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });

    // --- select the single conversation and extract -----------------------
    await page.getByRole("link", { name: "Select conversations →" }).click();
    const row = page.getByTestId("conversation-row").filter({ hasText: "Synthetic Clusters" });
    await row.locator('input[type="checkbox"]').check();
    await page.getByTestId("extract-button").click();
    await expect(page.getByTestId("extract-job-status")).toContainText("succeeded", {
      timeout: 20_000,
    });

    // --- run the analysis pipeline so clusters exist to generate from -----
    await page.goto("/clusters");
    await page.getByTestId("run-analysis").click();
    await expect(page.getByTestId("analysis-done")).toBeVisible({
      timeout: ANALYSIS_TIMEOUT_MS,
    });

    // --- generate projects from the clusters ------------------------------
    // Read the starting count from the API response body, not the DOM — the
    // dev DB is long-lived (prior runs leave projects behind), and counting
    // rendered cards right after navigation races the initial React Query
    // fetch/render.
    const initialListResponse = page.waitForResponse(
      (response) => response.url().includes("/api/projects") && response.request().method() === "GET",
    );
    await page.goto("/projects");
    const cardsBefore = ((await (await initialListResponse).json()) as { total: number }).total;
    const cards = page.getByTestId("project-card");

    await page.getByTestId("generate-open").click();
    const clusterCheckboxes = page.getByTestId("generate-cluster-checkbox");
    await expect(clusterCheckboxes.first()).toBeVisible({ timeout: 20_000 });
    const clusterCount = await clusterCheckboxes.count();
    for (let index = 0; index < clusterCount; index += 1) {
      await clusterCheckboxes.nth(index).check();
    }
    await page.getByTestId("generate-count").fill("3");
    await page.getByTestId("generate-start").click();
    await expect(page.getByTestId("generation-status")).toContainText("Generation complete", {
      timeout: JOB_TIMEOUT_MS,
    });
    await expect(cards).toHaveCount(cardsBefore + 3, { timeout: 20_000 });

    // Transparent scoring: every card renders sub-score bars with rationales.
    const firstCard = cards.first();
    await expect(firstCard.getByTestId("score-bars")).toBeVisible();
    await expect(firstCard.getByTestId("score-rationale-career_alignment")).not.toHaveText("");
    await expect(firstCard.getByTestId("score-rationale-recruiter_appeal")).not.toHaveText("");

    // --- weight sliders re-rank client-side, no generation API call -------
    const generateRequests: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/projects/generate")) {
        generateRequests.push(request.url());
      }
    });
    // Weights persist across runs, so drive the slider to known values via
    // the keyboard (Home = min) rather than relying on its starting point.
    const allScores = async () =>
      (await page.getByTestId("project-score").allInnerTexts()).join(",");
    const feasibilitySlider = page.getByTestId("weight-slider-feasibility");
    await feasibilitySlider.focus();
    await page.keyboard.press("Home");
    await expect(page.getByTestId("weight-value-feasibility")).toContainText("×0.0");
    const scoresAtZero = await allScores();
    for (let press = 0; press < 5; press += 1) {
      await page.keyboard.press("ArrowRight");
    }
    await expect(page.getByTestId("weight-value-feasibility")).toContainText("×0.5");
    // Every project's total strictly grows with the feasibility weight, so
    // the rendered score column must change — recomputed purely client-side.
    await expect.poll(allScores, { timeout: 10_000 }).not.toBe(scoresAtZero);
    expect(generateRequests).toHaveLength(0);

    await page.getByTestId("weights-save").click();
    await expect(page.getByTestId("weights-saved")).toBeVisible({ timeout: 20_000 });

    // --- side-by-side comparison of two projects --------------------------
    await cards.nth(0).getByTestId("project-select").check();
    await cards.nth(1).getByTestId("project-select").check();
    await page.getByTestId("compare-open").click();
    await expect(page.getByTestId("compare-grid")).toBeVisible();
    await expect(page.getByTestId("compare-header")).toHaveCount(2);
    for (const dimension of [
      "career_alignment",
      "technical_depth",
      "originality",
      "feasibility",
      "recruiter_appeal",
    ]) {
      await expect(page.getByTestId(`compare-row-${dimension}`)).toBeVisible();
    }
    await page.getByRole("button", { name: "Close" }).click();

    // --- combine the two selected ideas into a linked child ---------------
    const combinedBefore = await page.getByTestId("project-combined-badge").count();
    await page.getByTestId("combine-start").click();
    await expect(page.getByTestId("generation-status")).toContainText("Generation complete", {
      timeout: JOB_TIMEOUT_MS,
    });
    await expect(cards).toHaveCount(cardsBefore + 4, { timeout: 20_000 });
    await expect(page.getByTestId("project-combined-badge")).toHaveCount(combinedBefore + 1, {
      timeout: 20_000,
    });

    // --- open the combined project's detail page --------------------------
    const combinedCard = cards
      .filter({ has: page.getByTestId("project-combined-badge") })
      .first();
    await combinedCard.getByTestId("project-title").click();
    await expect(page).toHaveURL(/\/projects\/\d+$/);
    await expect(page.getByTestId("detail-combined-badge")).toBeVisible({ timeout: 20_000 });

    // --- field editing persists across a reload ---------------------------
    const editedTitle = `Edited combined project ${marker}`;
    await page.getByTestId("detail-edit").click();
    await page.getByTestId("detail-title-input").fill(editedTitle);
    await page.getByTestId("detail-save").click();
    await expect(page.getByTestId("project-detail-title")).toHaveText(editedTitle);
    await page.reload();
    await expect(page.getByTestId("project-detail-title")).toHaveText(editedTitle, {
      timeout: 20_000,
    });

    // --- roadmap milestones: add, reorder, persist ------------------------
    const stepA = `Step A ${marker}`;
    const stepB = `Step B ${marker}`;
    await page.getByTestId("milestone-title-input").fill(stepA);
    await page.getByTestId("milestone-add").click();
    await expect(
      page.getByTestId("milestone-row").filter({ hasText: stepA }),
    ).toBeVisible({ timeout: 20_000 });
    await page.getByTestId("milestone-title-input").fill(stepB);
    await page.getByTestId("milestone-add").click();
    const rowB = page.getByTestId("milestone-row").filter({ hasText: stepB });
    await expect(rowB).toBeVisible({ timeout: 20_000 });

    const titleOrder = async () => {
      const titles = await page.getByTestId("milestone-title").allInnerTexts();
      return { a: titles.indexOf(stepA), b: titles.indexOf(stepB) };
    };
    const initial = await titleOrder();
    expect(initial.a).toBeGreaterThanOrEqual(0);
    expect(initial.b).toBe(initial.a + 1); // created in order, appended at the end

    await rowB.getByTestId("milestone-up").click();
    // B swaps into A's old slot.
    await expect.poll(async () => (await titleOrder()).b, { timeout: 20_000 }).toBe(initial.a);
    const swapped = await titleOrder();
    expect(swapped.b).toBeLessThan(swapped.a);

    await page.reload();
    await expect(
      page.getByTestId("milestone-row").filter({ hasText: stepB }),
    ).toBeVisible({ timeout: 20_000 });
    const persisted = await titleOrder();
    expect(persisted.b).toBeLessThan(persisted.a); // reorder persisted

    // --- advisor review: five sections, regeneration versions it ----------
    const versionButtons = page.locator('[data-testid^="advisor-version-"]');
    await page.getByTestId("advisor-request").click();
    await expect(page.getByTestId("advisor-review")).toBeVisible({ timeout: JOB_TIMEOUT_MS });
    for (const section of [
      "advisor-commonality",
      "advisor-comparative",
      "advisor-recruiter",
      "advisor-prerequisites",
      "advisor-week-by-week",
    ]) {
      await expect(page.getByTestId(section)).toBeVisible();
    }
    await expect(page.getByTestId("advisor-request")).toHaveText("Regenerate review", {
      timeout: JOB_TIMEOUT_MS,
    });
    const versionsAfterFirst = await versionButtons.count();

    await page.getByTestId("advisor-request").click();
    // A fresh project goes 1 -> 2 versions (the picker appears at 2); a
    // project that already had reviews gains exactly one more.
    const expectedVersions = versionsAfterFirst === 0 ? 2 : versionsAfterFirst + 1;
    await expect(versionButtons).toHaveCount(expectedVersions, { timeout: JOB_TIMEOUT_MS });
    await expect(page.getByTestId("advisor-review")).toBeVisible();
  });
});
