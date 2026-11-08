import { describe, expect, it } from "vitest";
import { mockPrivacy, mockResult } from "./fixtures";
import {
  activitySummary,
  isRedactionTag,
  maskLinks,
  nextStep,
  primaryAction,
  receivedLines,
  redactedText,
  redactionMatches,
  splitRedacted,
} from "./present";

describe("result wording", () => {
  it("says what was checked, and never that the account is fine", () => {
    const scam = mockResult("scenario1").result!;
    expect(activitySummary(scam)).toMatch(/no new payees or unusual transfers/i);
    expect(nextStep(scam)).toBe("Don’t use the link in this text.");
    expect(nextStep(mockResult("scenario3").result!)).toBe("Use the official app to review your bill.");
    expect(nextStep(mockResult("legit").result!)).not.toMatch(/account is fine|this is safe/i);
    expect(primaryAction(mockResult("scenario3").result!)).toBe("open_official_app");
    expect(primaryAction(scam)).toBe("block_sender");
  });

  it("hides full links and phone numbers from what a tool received", () => {
    expect(maskLinks("Pay now: https://tmobile-billpay-now.com/pay")).toBe("Pay now: <URL_1>");
    const nemotron = mockPrivacy().recipients.find((r) => r.recipient === "nemotron")!;
    const lines = receivedLines({
      ...nemotron,
      received_fields: [...nemotron.received_fields, "note"],
      payload: { ...nemotron.payload, note: "call 555-010-4477 or https://example.com" },
    });
    expect(lines.join(" ")).not.toMatch(/https?:|555/);
    expect(redactedText(mockPrivacy())).toContain("<PERSON>");
    const raw = "Capital One Alert: unusual sign-in for Linda. Your account will be locked in 2 hours. Verify now: https://capone-verify-alert.com/verify";
    expect(redactionMatches(raw, redactedText(mockPrivacy())!)).toBe(true);
    expect(redactionMatches("Hi Mom, landed safe. Will call you after dinner tonight.", redactedText(mockPrivacy())!)).toBe(false);
  });

  it("recognizes every A3 tag shape, including lowercase hex phone hashes", () => {
    for (const tag of ["<PERSON>", "<URL_1>", "<ACCOUNT_DIGITS>", "<UNKNOWN_SENDER>", "<PHONE_HASH_2ae6f01c9b3d4e57>", "<PHONE_HASH_2ae6…>"]) {
      expect(isRedactionTag(tag)).toBe(true);
    }
    for (const text of ["<b>", "<phone_hash_2ae6>", "< PERSON>", "<PERSON> hi"]) expect(isRedactionTag(text)).toBe(false);
    expect(splitRedacted("Call <PHONE_HASH_2ae6f01c> now")).toEqual(["Call ", "<PHONE_HASH_2ae6f01c>", " now"]);
    expect(redactionMatches("Call 555-010-4477 about your parcel today please", "Call <PHONE_HASH_2ae6f01c> about your parcel today please")).toBe(true);
  });
});
