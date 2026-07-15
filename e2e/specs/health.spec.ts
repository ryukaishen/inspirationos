import { expect, test } from "@playwright/test";

test.describe("foundation: health + demo job", () => {
  test("health endpoint is ok through the frontend proxy", async ({ request }) => {
    const response = await request.get("/api/health");
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: "ok", db: "healthy", redis: "healthy" });
  });

  test("home page renders healthy services", async ({ page }) => {
    await page.goto("/");
    const health = page.getByTestId("health-status");
    await expect(health).toContainText("All services healthy");
    await expect(health).toContainText("Database");
    await expect(health).toContainText("Redis");
  });

  test("demo job transitions queued/running to succeeded via polling", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Run demo job" }).click();

    const status = page.getByTestId("job-status");
    // The default demo job runs ~5s in the worker; the UI polls every 2s,
    // so the intermediate running state must become visible...
    await expect(status).toHaveText(/queued|running/);
    await expect(status).toHaveText("running", { timeout: 10_000 });
    // ...and it must finish.
    await expect(status).toHaveText("succeeded", { timeout: 20_000 });
    await expect(page.getByTestId("job-progress")).toHaveText("10 / 10");
  });
});
