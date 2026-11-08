import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import type { ResultPoll } from "../src/types";

test("all three authored scenarios use the real API, recover the purchase, and disclose privacy", async ({ page, request }) => {
  const errors: string[] = [];
  const taps: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("request", req => {
    if (req.method() === "POST" && /\/api\/(?:actions|transactions\/.*\/confirm|messages\/.*\/clicked)/.test(req.url())) taps.push(req.url());
  });
  const health = await (await request.get("/api/health")).json();
  expect(health.use_mocks).toBe(false);
  expect(Object.values(health.mocked_routes).every(mocked => !mocked)).toBe(true);
  expect((await request.post("/api/demo/reset")).ok()).toBe(true);

  await page.goto("/inbox");
  const bank = page.locator(".inbox-message").filter({ hasText: "Capital One Alert" }).first();
  await expect(bank).toBeEnabled();
  await bank.click();
  await expect(page.locator(".result-card .verdict-badge")).toContainText(/likely a scam/i);
  const first: ResultPoll = await (await request.get("/api/messages/msg_0001/result")).json();
  expect(first.status).toBe("done");
  expect(first.mode).toBe("check");
  expect(first.result!.plan).toContain("nessie_recent_activity");
  expect(first.result!.was_this_you).toEqual([]);
  await page.getByRole("button", { name: "How we checked", exact: true }).click();
  await expect(page.locator(".trail-list")).toContainText(/activity/i);
  await page.goto("/privacy/msg_0001");
  await expect(page.locator(".redacted-message")).toContainText("<PERSON>");
  const privacy = await (await request.get("/api/privacy/msg_0001")).json();
  expect(JSON.stringify(privacy)).not.toContain("Linda");
  expect(JSON.stringify(privacy)).not.toContain("Unknown Payee");
  expect(JSON.stringify(privacy)).not.toContain("https://capone-verify-alert.com/verify");
  expect(privacy.recipients.some((recipient: { recipient: string }) => recipient.recipient === "nemotron")).toBe(true);

  await page.goto("/result/msg_0003");
  await expect(page.locator(".result-card .verdict-badge")).toContainText(/likely a scam/i);
  const third: ResultPoll = await (await request.get("/api/messages/msg_0003/result")).json();
  expect(third.result!.plan).toContain("nessie_bill_status");
  expect(third.result!.plan).not.toEqual(first.result!.plan);
  const bill = third.trail.find(entry => entry.tool === "nessie_bill_status")!.finding!;
  expect(bill).toContain("paid on 2026-11-01");
  expect(bill).toContain("$0.00 due now");
  const campaigns = await (await request.get("/api/campaigns")).json();
  expect(campaigns.some((campaign: { count_total: number }) => campaign.count_total > 1)).toBe(true);
  await page.goto("/campaigns");
  await expect(page.locator(".campaign-card").first()).toBeVisible();
  await page.locator(".campaign-card").first().getByRole("button", { name: "View the pattern" }).click();
  await expect(page.locator(".campaign-detail").first()).toContainText("The shared pattern");
  const metrics = await (await request.get("/api/metrics")).json();
  await page.goto("/accuracy");
  await expect(page.getByRole("heading", { name: "Every category counts." })).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(metrics.categories.length);
  await page.getByRole("button", { name: "Public SMS", exact: true }).click();
  await expect(page.getByText(metrics.public_set.dataset, { exact: true })).toBeVisible();
  await expect(page.getByText("What this split means.", { exact: true })).toBeVisible();
  expect(taps).toEqual([]);

  await page.goto("/recovery/msg_0001");
  await page.getByRole("button", { name: "I clicked and entered my info", exact: true }).click();
  await expect(page.getByText("$900", { exact: true })).toBeVisible();
  await expect(page.getByText("Unknown Payee", { exact: true })).toBeVisible();
  await expect(page.getByText("17 minutes after the text", { exact: true })).toBeVisible();
  const second: ResultPoll = await (await request.get("/api/messages/msg_0001/result")).json();
  expect(second.mode).toBe("recovery");
  expect(second.result!.verdict).toBe("likely_scam");
  expect(second.result!.was_this_you).toContain("txn_28");
  expect(second.result!.replan).toBe(true);
  expect(second.result!.actions).toContain("freeze_card");
  expect(second.was_this_you_items.some(item => item.amount === 900 && item.payee === "Unknown Payee")).toBe(true);
  expect(taps.filter(url => url.includes("/confirm"))).toEqual([]);
  const [confirmed] = await Promise.all([
    page.waitForResponse(response => response.url().includes("/transactions/txn_28/confirm")),
    page.getByRole("button", { name: /No, I don’t recognize this/ }).click(),
  ]);
  expect(confirmed.ok()).toBe(true);
  expect((await confirmed.json()).recorded).toBe(true);
  await expect(page.getByText("You’re in control.", { exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(3);
  expect(taps.filter(url => url.includes("/confirm"))).toHaveLength(1);
  expect(taps.filter(url => url.endsWith("/actions"))).toEqual([]);
  expect(errors).toEqual([]);

  const mode = process.env.GATE_MODE || "replay";
  const report = { mode, observed_at: new Date().toISOString(), use_mocks: false, classifier: "frozen local L7 v2",
    plans: { bank: first.result!.plan, recovery: second.result!.plan, bill: third.result!.plan },
    verdicts: [first.result!.verdict, second.result!.verdict, third.result!.verdict],
    recovery: { ref: "txn_28", amount: 900, minutes_after_message: 17, confirmation_recorded_after_tap: true },
    bill, privacy_model_bank_details_absent: true, campaign_view_checked: true, real_accuracy_page_checked: true,
    browser_errors: errors,
    replay_outbound_network_blocked: mode === "replay", public_search: "explicitly unavailable" };
  mkdirSync("../eval", { recursive: true });
  writeFileSync(`../eval/app_gate_${mode}.json`, JSON.stringify(report, null, 2)+"\n");
});
