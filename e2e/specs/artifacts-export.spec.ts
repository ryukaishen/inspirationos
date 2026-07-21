import fs from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", ".fixtures");

// Analysis runs offline (AI_PROVIDER=mock; embedding provider mock in CI or
// local fastembed on dev stacks — first run downloads the model once).
const ANALYSIS_TIMEOUT_MS = 240_000;
const JOB_TIMEOUT_MS = 60_000;

interface ProjectExportJson {
  id: number;
  artifacts: { kind: string; content_md: string }[];
}

test.describe("career artifacts and export", () => {
  test.describe.configure({ mode: "serial" });

  test("generate README, export Markdown and JSON, verify file contents", async ({ page }) => {
    test.setTimeout(ANALYSIS_TIMEOUT_MS + 180_000);

    // --- upload + scan (own zip: checksum-distinct from clusters/projects) --
    await page.goto("/import");
    await page.setInputFiles('input[type="file"]', path.join(FIXTURES, "artifacts.zip"));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/import\/\d+$/);
    await expect(page.getByTestId("import-status")).toHaveText("scanned", { timeout: 20_000 });

    // --- select the single conversation and extract -------------------------
    await page.getByRole("link", { name: "Select conversations →" }).click();
    const row = page.getByTestId("conversation-row").filter({ hasText: "Synthetic Clusters" });
    await row.locator('input[type="checkbox"]').check();
    await page.getByTestId("extract-button").click();
    await expect(page.getByTestId("extract-job-status")).toContainText("succeeded", {
      timeout: 20_000,
    });

    // --- run the analysis pipeline so clusters exist to generate from -------
    await page.goto("/clusters");
    await page.getByTestId("run-analysis").click();
    await expect(page.getByTestId("analysis-done")).toBeVisible({
      timeout: ANALYSIS_TIMEOUT_MS,
    });

    // --- generate one project from the clusters ------------------------------
    await page.goto("/projects");
    await page.getByTestId("generate-open").click();
    const clusterCheckboxes = page.getByTestId("generate-cluster-checkbox");
    await expect(clusterCheckboxes.first()).toBeVisible({ timeout: 20_000 });
    const clusterCount = await clusterCheckboxes.count();
    for (let index = 0; index < clusterCount; index += 1) {
      await clusterCheckboxes.nth(index).check();
    }
    await page.getByTestId("generate-count").fill("1");
    await page.getByTestId("generate-start").click();
    await expect(page.getByTestId("generation-status")).toContainText("Generation complete", {
      timeout: JOB_TIMEOUT_MS,
    });

    // --- open the newest project's detail page --------------------------------
    const cards = page.getByTestId("project-card");
    await expect(cards.first()).toBeVisible({ timeout: 20_000 });
    await cards.first().getByTestId("project-title").click();
    await expect(page).toHaveURL(/\/projects\/\d+$/);
    const projectId = Number(page.url().match(/\/projects\/(\d+)$/)?.[1]);
    const projectTitle = (await page.getByTestId("project-detail-title").innerText()).trim();

    // --- generate the README career artifact ----------------------------------
    await page.getByTestId("career-artifact-tab-readme").click();
    await page.getByTestId("career-artifact-request").click();
    await expect(page.getByTestId("career-artifact-content")).toBeVisible({
      timeout: JOB_TIMEOUT_MS,
    });

    // --- export Markdown: download and verify the file contains the title ----
    await page.getByTestId("export-markdown-request").click();
    const [markdownDownload] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("export-markdown-download").click({ timeout: JOB_TIMEOUT_MS }),
    ]);
    const markdownPath = await markdownDownload.path();
    expect(markdownPath).not.toBeNull();
    const markdownContent = await fs.readFile(markdownPath as string, "utf-8");
    expect(markdownContent).toContain(projectTitle);
    expect(markdownContent).toContain("Readme");

    // --- export JSON: download and verify it parses with the project id ------
    await page.getByTestId("export-json-request").click();
    const [jsonDownload] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("export-json-download").click({ timeout: JOB_TIMEOUT_MS }),
    ]);
    const jsonPath = await jsonDownload.path();
    expect(jsonPath).not.toBeNull();
    const jsonContent = JSON.parse(
      await fs.readFile(jsonPath as string, "utf-8"),
    ) as ProjectExportJson;
    expect(jsonContent.id).toBe(projectId);
    expect(jsonContent.artifacts.some((artifact) => artifact.kind === "readme")).toBe(true);
  });
});
