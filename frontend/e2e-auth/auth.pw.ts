import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { authEnv } from "../playwright.auth.config";

const PASSWORD = "e2e demo password, long enough";

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits), so the test can type a real code. */
function totp(secretBase32: string, offsetSteps = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secretBase32.replace(/=+$/, "")) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + offsetSteps));
  const mac = createHmac("sha1", key).update(counter).digest();
  const offset = mac[mac.length - 1] & 0xf;
  return ((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

function createDemoUser(): string {
  const out = execFileSync(process.env.E2E_PYTHON || "python", ["-m", "scripts.create_user", "--demo"], {
    cwd: "../backend",
    env: { ...process.env, ...authEnv, SENTINEL_NEW_PASSWORD: PASSWORD },
    encoding: "utf-8",
  });
  return out.match(/type the secret: ([A-Z2-7]+)/)![1];
}

test("sign in with password + code, use the app, add a passkey, sign out, sign back in with the passkey", async ({ page }) => {
  const secret = createDemoUser();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // Chromium's virtual authenticator stands in for Windows Hello / Touch ID.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true },
  });

  // Signed out: the app shows sign-in, not the inbox.
  await page.goto("/inbox");
  await expect(page.getByRole("button", { name: "Sign in with a passkey" })).toBeVisible();
  await expect(page.locator(".inbox-message")).toHaveCount(0);

  // A wrong password gets the one generic message.
  await page.getByRole("button", { name: "Use a password and code instead" }).click();
  await page.getByLabel("Username").fill("demo");
  await page.getByLabel("Password").fill("not the password at all");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toContainText("didn’t work");

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel(/6-digit code/).fill(totp(secret));
  await page.getByRole("button", { name: "Sign in" }).click();

  // Signed in: the demo inbox and scenario 1 work as before.
  const message = page.locator(".inbox-message").filter({ hasText: "Capital One Alert" }).first();
  await expect(message).toBeEnabled({ timeout: 20_000 });
  await message.click();
  await expect(page.locator(".result-card .verdict-badge")).toContainText(/likely a scam/i);

  // Session cookies are HttpOnly: the page can't read them; only the CSRF token is visible.
  const visible = await page.evaluate(() => document.cookie);
  expect(visible).not.toContain("sa_at");
  expect(visible).not.toContain("sa_rt");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(/eyJ/);
  const cookies = await page.context().cookies();
  const access = cookies.find((c) => c.name === "sa_at")!;
  expect(access.httpOnly && access.secure && access.sameSite === "Strict").toBe(true);

  // Add a passkey, sign out, sign back in with it.
  await expect(page.locator(".account-line")).toContainText("no passkey yet");
  await page.getByRole("button", { name: "Add a passkey" }).click();
  await expect(page.locator(".account-line")).toContainText("Passkey added");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in with a passkey" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(page.locator(".inbox-message, .result-card").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".account-line")).toContainText("passkey on");

  expect(errors).toEqual([]);
});
