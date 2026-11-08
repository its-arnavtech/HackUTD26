// Display copy derived from contract data (DATA_SPEC 3.3, 3.4 and the privacy view).
// The design lab carried these as extra fields; they stay UI-side so the contracts don't change.
import type { Action, AgentResult, AgentMode, PrivacyRecipient, PrivacyView, RedactionCounts } from "./types";

const BANK_TOOLS = ["nessie_recent_activity", "nessie_bill_status"] as const;

/** The evidence line beside the wallet icon: the check that speaks to the customer's account, or the first check. */
export function activitySummary(result: AgentResult): string {
  const bank = result.evidence.find((e) => (BANK_TOOLS as readonly string[]).includes(e.tool));
  const finding = bank?.finding ?? result.evidence[0]?.finding;
  if (finding) return sentence(finding);
  if (result.verdict === "unsure") return "We couldn’t confirm all the details.";
  return "Your bank activity wasn’t checked for this message.";
}

/**
 * A3's redaction tags: `<PERSON>`, `<URL_1>`, `<ACCOUNT_DIGITS>`, and `<PHONE_HASH_2ae6…>`, whose digest is
 * lowercase hex (a display may shorten it with an ellipsis). The name is uppercase; segments after it may not be.
 */
const TAG = "<[A-Z][A-Z0-9]*(?:_[A-Za-z0-9…]+)*>";

export const isRedactionTag = (part: string) => new RegExp(`^${TAG}$`).test(part);

/** Splits redacted text into plain runs and tags, in order, so each tag can render as a chip. */
export const splitRedacted = (text: string) => text.split(new RegExp(`(${TAG})`, "g")).filter((part) => part !== "");

/** True when `redacted` is the redacted form of this message, not another fixture's text. */
export function redactionMatches(raw: string, redacted: string): boolean {
  const pieces = redacted
    .split(new RegExp(TAG))
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter((part) => part.length >= 12);
  return pieces.length > 0 && pieces.every((part) => raw.includes(part));
}

/** One plain next step. Contact steps only ever point to the official app or the card. */
export function nextStep(result: AgentResult, mode: AgentMode = "check"): string {
  if (mode === "recovery" && result.was_this_you.length > 0) return "Review the activity, then take it step by step.";
  if (result.verdict === "likely_scam") {
    if (result.evidence.some((e) => e.tool === "nessie_bill_status")) return "Use the official app to review your bill.";
    if (result.evidence.some((e) => e.tool === "check_link")) return "Don’t use the link in this text.";
    return "Don’t reply to this text or pay from it.";
  }
  if (result.verdict === "unsure") return "Use the official app to check for yourself.";
  return "If anything feels off, use the official app or call the number on the back of your card.";
}

export const actionLabels: Record<Action, string> = {
  block_sender: "Block this sender",
  report_spam: "Report this text",
  call_number_on_card: "Call the number on your card",
  open_official_app: "Use the official app",
  freeze_card: "Review your card controls",
  change_password: "Change your password",
  alert_trusted_contact: "Tell someone you trust",
  ignore: "Dismiss this message",
};

/** Shown after the customer taps an action. Nothing here acts on money. */
export const actionReceipts: Record<Action, string> = {
  block_sender: "Sender blocked in this demo.",
  report_spam: "Text reported in this demo.",
  call_number_on_card: "Call the number on the back of your card.",
  open_official_app: "Open the official app on your phone.",
  freeze_card: "Use the official app to review card controls.",
  change_password: "Open the official app to change your password.",
  alert_trusted_contact: "Ask someone you trust to sit with you.",
  ignore: "Message dismissed in this demo.",
};

/** Shown on the primary button once its receipt is in. */
export const actionDone: Partial<Record<Action, string>> = {
  block_sender: "Sender blocked",
  report_spam: "Text reported",
  ignore: "Dismissed",
};

/**
 * The one primary action on the card. A billing result leads with the official app,
 * matching the lab, because the next step is to review the bill there.
 */
export function primaryAction(result: AgentResult): Action | undefined {
  if (result.evidence.some((e) => e.tool === "nessie_bill_status") && result.actions.includes("open_official_app")) {
    return "open_official_app";
  }
  return result.actions[0];
}

/** Hide full links in message text shown on the phone. The privacy panel shows the redacted form. */
export function maskLinks(text: string): string {
  return text.replace(/https?:\/\/\S+/gi, "<URL_1>");
}

const hiddenValue = /https?:\/\/|www\.|(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}/;

/** What one recipient was given, in words. Full links and phone numbers are left out. */
export function receivedLines(recipient: PrivacyRecipient): string[] {
  return recipient.received_fields.map((field) => {
    const value = recipient.payload[field];
    const label = fieldLabel(field);
    if (field === "text_redacted" || typeof value === "string" && (value.length > 180 || hiddenValue.test(value))) {
      return label;
    }
    if (typeof value === "string" && value) return `${label}: ${value}`;
    if (typeof value === "number" || typeof value === "boolean") return `${label}: ${value}`;
    return label;
  });
}

const countWords: Record<keyof RedactionCounts, [string, string]> = {
  PERSON: ["name", "names"],
  PHONE: ["personal number", "personal numbers"],
  ACCOUNT_DIGITS: ["set of account digits", "sets of account digits"],
  ADDRESS: ["address", "addresses"],
  EMAIL: ["email address", "email addresses"],
};

export function redactionCounts(counts: RedactionCounts): string[] {
  return (Object.keys(countWords) as (keyof RedactionCounts)[])
    .filter((key) => counts[key] > 0)
    .map((key) => `${counts[key]} ${countWords[key][counts[key] === 1 ? 0 : 1]} hidden`);
}

const recipientLabels: Record<string, string> = {
  classifier: "Message classifier",
  nemotron: "Nemotron, the AI planner",
  gemini: "Public-report lookup (Gemini)",
  public_scam_reports: "Public-report lookup (Gemini)",
  check_link: "Link check",
  check_sender: "Sender check",
  match_campaign: "Similar-message check",
  nessie_recent_activity: "Bank activity check",
  nessie_bill_status: "Bill status check",
};

const fieldLabels: Record<string, string> = {
  text_redacted: "The message, with personal details hidden",
  features: "Message features: deadline, threat, what it asks for",
  sender: "The kind of sender and a scrambled sender tag",
  urls: "Link domains, not the full links",
  classifier: "The classifier’s category and score",
  customer_context: "Whether a bank account is linked",
  url_id: "A link reference, not the link itself",
  claimed_brand: "The company the text claims to be",
  days: "How many days of activity to check",
  since: "When the text arrived",
  payee: "The company name on the bill",
  message_id: "A message reference",
  scam_category: "The kind of scam",
  link_domain: "The link’s domain",
  lure_phrase: "A short generic phrase, not your message",
};

const humanize = (key: string) => {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

export const recipientLabel = (r: PrivacyRecipient) => recipientLabels[r.recipient] || humanize(r.recipient);
export const fieldLabel = (field: string) => fieldLabels[field] || humanize(field);

/** The company a model was told the text claims to be, when the privacy log has it. */
export function claimedBrand(view: PrivacyView): string | undefined {
  for (const recipient of view.recipients) {
    const direct = recipient.payload.claimed_brand;
    if (typeof direct === "string" && direct) return direct;
    const sender = recipient.payload.sender;
    if (sender && typeof sender === "object" && !Array.isArray(sender)) {
      const brand = (sender as { claimed_brand?: unknown }).claimed_brand;
      if (typeof brand === "string" && brand) return brand;
    }
  }
  return undefined;
}

/** The redacted text exactly as the first model or tool received it. */
export function redactedText(view: PrivacyView): string | undefined {
  for (const r of view.recipients) {
    const text = r.payload.text_redacted;
    if (typeof text === "string") return text;
  }
  return undefined;
}

function sentence(text: string) {
  const trimmed = text.trim();
  const capped = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capped) ? capped : `${capped}.`;
}
