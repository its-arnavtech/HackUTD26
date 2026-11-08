import { expect, test } from "@playwright/test";

test("scenario 1 opens its result, explains the checks, and shows the privacy boundary", async ({ page, request }) => {
  await request.post("/api/demo/reset");
  const errors: string[] = [];
  const actions: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", req => {
    if (req.method() === "POST" && /\/api\/(actions|transactions\/.*\/confirm)/.test(req.url())) actions.push(req.url());
  });

  await page.goto("/inbox");
  const message = page.locator(".inbox-message").filter({ hasText: "Capital One Alert" }).first();
  await expect(message).toBeEnabled({ timeout: 20_000 });
  await message.click();
  await expect(page).toHaveURL(/\/result\/msg_0001$/);
  await expect(page.locator(".result-card .verdict-badge")).toContainText(/likely a scam/i);
  await expect(page.locator(".evidence-summary")).toContainText(/no (?:new payees|unusual activity)/i);
  await expect(page.locator(".result-screen")).not.toContainText(/https?:\/\/|capone-verify-alert\.com/);

  await page.getByRole("button", { name: "How we checked", exact: true }).click();
  await expect(page).toHaveURL(/\/trail\/msg_0001$/);
  await expect(page.locator(".trail-list")).toContainText(/link|website/i);
  await expect(page.locator(".trail-list")).toContainText(/activity/i);
  await page.getByRole("button", { name: "Back to your result" }).click();
  await expect(page.locator(".result-card")).toBeVisible();

  await page.goto("/privacy/msg_0001");
  await expect(page.locator(".redacted-message")).toContainText("<PERSON>");
  await expect(page.getByRole("heading", { name: "Nemotron, the AI planner", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Bank activity check", exact: true })).toBeVisible();
  await expect(page.locator(".privacy-screen")).toContainText(/sender.s phone number/i);
  expect(actions).toEqual([]); // Browsing a result never initiates a protective action.
  expect(errors).toEqual([]);
});
