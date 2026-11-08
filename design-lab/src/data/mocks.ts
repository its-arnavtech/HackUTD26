import type {
  AgentResult,
  Campaign,
  DemoMessage,
  Metrics,
  PrivacyReport,
  RecoveryItem,
  Scenario,
  TrailEntry,
  Transaction,
} from "../types";
const at = "2026-11-08T09:14:00-06:00";
const bankMessage: DemoMessage = {
  id: "msg_0142",
  brand: "Capital One",
  preview: "Unusual sign-in. Your account will be locked in 2 hours…",
  text: "Capital One Alert: unusual sign-in for <PERSON>, account <ACCOUNT_DIGITS>. Your account will be locked in 2 hours. Verify now: <URL_1>",
  received_at: at,
  status: "done",
  verdict: "likely_scam",
  authored: true,
};
const bankResult: AgentResult = {
  plan: ["check_link", "check_sender", "nessie_recent_activity"],
  verdict: "likely_scam",
  confidence_words: "very likely",
  reason: "The link and sender don’t match Capital One.",
  evidence: [
    { tool: "check_link", finding: "The link does not belong to Capital One." },
    {
      tool: "check_sender",
      finding: "The sender does not match a known official channel.",
    },
    {
      tool: "nessie_recent_activity",
      finding: "No unusual activity found in the last 7 days.",
    },
  ],
  actions: ["block_sender", "report_spam", "call_number_on_card"],
  was_this_you: [],
  replan: false,
};
const entry = (
  step: number,
  kind: TrailEntry["kind"],
  finding: string,
  why: string,
  tool?: TrailEntry["tool"],
): TrailEntry => ({
  step,
  kind,
  tool,
  finding,
  why,
  ms: kind === "tool" ? 412 : 0,
  at: `2026-11-08T09:14:0${step}-06:00`,
});
const bankTrail: TrailEntry[] = [
  entry(
    1,
    "plan",
    "Check the link, sender, then recent account activity.",
    "The text claims to be your bank.",
  ),
  entry(
    2,
    "tool",
    "The link does not belong to Capital One.",
    "A look-alike link can lead to a fake sign-in page.",
    "check_link",
  ),
  entry(
    3,
    "tool",
    "The sender does not match a known official channel.",
    "We compared the sender with known brand channels.",
    "check_sender",
  ),
  entry(
    4,
    "tool",
    "No unusual activity found in the last 7 days.",
    "We checked 23 items across two linked accounts.",
    "nessie_recent_activity",
  ),
  entry(
    5,
    "verdict",
    "Very likely a scam.",
    "The link and sender checks agree.",
  ),
];
const redaction = {
  counts: { PERSON: 1, PHONE: 1, ACCOUNT_DIGITS: 1, ADDRESS: 0, EMAIL: 0 },
  kept: ["brand", "domain", "deadline"],
};
export const scenarios: Record<string, Scenario> = {
  bank: {
    id: "bank",
    title: "The account-lock text",
    message: bankMessage,
    result: bankResult,
    trail: bankTrail,
    next_step: "Don’t use the link in this text.",
    activity_summary: "We found no unusual activity in the last 7 days.",
    redaction,
  },
  recovery: {
    id: "recovery",
    title: "After entering information",
    message: bankMessage,
    result: {
      ...bankResult,
      plan: ["nessie_recent_activity"],
      was_this_you: ["txn_3"],
      replan: true,
    },
    trail: [
      ...bankTrail,
      entry(
        6,
        "replan",
        "Check activity since the text arrived.",
        "You told us you entered your information.",
      ),
      entry(
        7,
        "tool",
        "A $900 transfer to a new payee needs your review.",
        "This transfer happened 17 minutes after the text.",
        "nessie_recent_activity",
      ),
    ],
    next_step: "Review the transfer, then take it step by step.",
    activity_summary: "One transfer needs your review.",
    redaction,
  },
  billing: {
    id: "billing",
    title: "The overdue-bill text",
    message: {
      id: "msg_0143",
      brand: "T-Mobile",
      preview: "Your bill is overdue. Pay $312 now to avoid suspension…",
      text: "T-Mobile: your bill is overdue. Pay $312 now to avoid suspension: <URL_1>",
      received_at: "2026-11-08T09:22:00-06:00",
      status: "done",
      verdict: "likely_scam",
      authored: true,
    },
    result: {
      plan: ["match_campaign", "nessie_bill_status", "public_scam_reports"],
      verdict: "likely_scam",
      confidence_words: "very likely",
      reason: "This text matches a fake billing campaign.",
      evidence: [
        {
          tool: "match_campaign",
          finding: "140 similar texts appeared in the last 24 hours.",
        },
        {
          tool: "nessie_bill_status",
          finding: "Your T-Mobile bill was paid on November 1.",
        },
        {
          tool: "public_scam_reports",
          finding: "Public guidance describes this payment-pressure pattern.",
        },
      ],
      actions: ["block_sender", "open_official_app", "report_spam"],
      was_this_you: [],
      replan: false,
    },
    trail: [
      entry(
        1,
        "plan",
        "Check similar texts, bill status, and public reports.",
        "This is a bill claim, so an activity check is not needed.",
      ),
      entry(
        2,
        "tool",
        "140 similar texts in the last 24 hours.",
        "We compared anonymized message patterns.",
        "match_campaign",
      ),
      entry(
        3,
        "tool",
        "Your T-Mobile bill was paid on November 1.",
        "We checked the completed bill in your linked account.",
        "nessie_bill_status",
      ),
      entry(
        4,
        "tool",
        "Public guidance describes this payment-pressure pattern.",
        "Supporting guidance helps explain the pattern.",
        "public_scam_reports",
      ),
      entry(
        5,
        "verdict",
        "Very likely a scam.",
        "The paid bill and campaign match contradict the message.",
      ),
    ],
    next_step: "Use the official app to review your bill.",
    activity_summary: "Your T-Mobile bill was paid on November 1.",
    redaction: {
      counts: { PERSON: 0, PHONE: 1, ACCOUNT_DIGITS: 0, ADDRESS: 0, EMAIL: 0 },
      kept: ["brand", "domain", "amount", "deadline"],
    },
  },
};
export const variants: Record<string, AgentResult> = {
  unsure: {
    ...bankResult,
    verdict: "unsure",
    confidence_words: "not sure",
    reason: "We couldn’t confirm who sent this text.",
    evidence: [
      { tool: "check_sender", finding: "The sender could not be confirmed." },
      { tool: "check_link", finding: "No link was available to check." },
    ],
    actions: ["open_official_app", "call_number_on_card"],
  },
  mixed: {
    ...bankResult,
    verdict: "unsure",
    confidence_words: "not sure",
    reason: "Some signs point to a scam, but we couldn’t confirm it.",
    evidence: [
      {
        tool: "check_link",
        finding: "The link looks like an official domain.",
      },
      {
        tool: "check_sender",
        finding: "The sender does not match a known official channel.",
      },
    ],
    actions: ["open_official_app", "call_number_on_card"],
  },
  safe: {
    ...bankResult,
    verdict: "likely_safe",
    confidence_words: "likely",
    reason: "The sender matches a known Capital One channel.",
    evidence: [
      {
        tool: "check_sender",
        finding: "The sender matches a known official channel.",
      },
      {
        tool: "nessie_recent_activity",
        finding: "The notice matches an activity item we checked.",
      },
    ],
    actions: ["open_official_app"],
    was_this_you: [],
  },
};
export const transaction: Transaction = {
  ref: "txn_3",
  type: "transfer",
  amount: 900,
  payee: "Unknown payee",
  at: "2026-11-08T09:31:00-06:00",
  minutes_after_message: 17,
  new_payee: true,
};
export const recoveryItems: RecoveryItem[] = [
  {
    id: "freeze",
    label: "Review your card controls",
    detail: "Use the official Capital One app to freeze your card if needed.",
    action: "freeze_card",
  },
  {
    id: "password",
    label: "Change your bank password",
    detail:
      "Open the official app yourself. Use a password you haven’t used before.",
    action: "change_password",
  },
  {
    id: "call",
    label: "Contact your bank",
    detail:
      "Call the number on the back of your card and tell them what happened.",
    action: "call_number_on_card",
  },
];
export const privacy: PrivacyReport = {
  redaction,
  text_redacted:
    "Capital One Alert: unusual sign-in for <PERSON>, account <ACCOUNT_DIGITS>. Your account will be locked in 2 hours. Verify now: <URL_1>",
  recipients: [
    {
      name: "Message classifier & Nemotron",
      received: [
        "Redacted message, brand, domain and deadline",
        "Tool summaries with references, not full bank records",
      ],
      never: [
        "Your name, personal number or account digits",
        "Payee names, account balances or full transactions",
      ],
    },
    {
      name: "Public-report lookup (Gemini)",
      received: [
        "Brand, scam category and link domain",
        "A generic phrase: “account locked, verify by link”",
      ],
      never: ["Your message text", "Personal details or bank activity"],
    },
  ],
  stored: ["Anonymized campaign fingerprint and time"],
  session_only: ["Message text", "Bank records"],
};
export const campaigns: Campaign[] = [
  {
    id: "camp_07",
    brand: "T-Mobile",
    count_today: 140,
    first_seen: "2026-11-06T10:00:00-06:00",
    template:
      "<BRAND>: your bill is overdue. Pay <AMOUNT> now to avoid suspension: <URL_1>",
    example_redacted:
      "T-Mobile: your bill is overdue. Pay $312 now to avoid suspension: <URL_1>",
    message_ids: ["msg_0143"],
    reports: [
      {
        publisher: "Authored demo guidance",
        date: "2026-10-29",
        claim: "Payment-pressure texts can imitate a familiar company.",
      },
    ],
  },
];
export const metrics: Metrics = {
  illustrative: true,
  dataset: "Held-out synthetic set · illustrative fixture",
  sample_size: 600,
  rows: [
    {
      category: "Bank impersonation",
      support: 120,
      baseline: { precision: 0.89, recall: 0.82, f1: 0.85 },
      sentinel: { precision: 0.96, recall: 0.94, f1: 0.95 },
    },
    {
      category: "Fake billing",
      support: 120,
      baseline: { precision: 0.84, recall: 0.79, f1: 0.81 },
      sentinel: { precision: 0.95, recall: 0.92, f1: 0.93 },
    },
    {
      category: "Delivery scams",
      support: 120,
      baseline: { precision: 0.91, recall: 0.86, f1: 0.88 },
      sentinel: { precision: 0.96, recall: 0.93, f1: 0.94 },
    },
    {
      category: "Prize & reward scams",
      support: 120,
      baseline: { precision: 0.87, recall: 0.83, f1: 0.85 },
      sentinel: { precision: 0.94, recall: 0.92, f1: 0.93 },
    },
    {
      category: "Legitimate messages",
      support: 120,
      baseline: { precision: 0.85, recall: 0.91, f1: 0.88 },
      sentinel: { precision: 0.96, recall: 0.98, f1: 0.97 },
    },
  ],
  false_positive_rate: { baseline: 0.09, sentinel: 0.02 },
  redaction: { before: 0.95, after: 0.94 },
};
