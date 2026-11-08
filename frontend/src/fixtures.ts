// Gallery and test fixtures, read straight from the backend's contract-validated mocks
// (backend/app/mocks, checked by backend/tests/test_api_mocks.py). Never fetched at runtime.
import campaignsJson from "../../backend/app/mocks/campaigns.json";
import inboxJson from "../../backend/app/mocks/inbox.json";
import metricsJson from "../../backend/app/mocks/metrics.json";
import privacyJson from "../../backend/app/mocks/privacy.json";
import resultLegitJson from "../../backend/app/mocks/result_legit.json";
import resultScenario1Json from "../../backend/app/mocks/result_scenario_1.json";
import resultScenario2Json from "../../backend/app/mocks/result_scenario_2.json";
import resultScenario3Json from "../../backend/app/mocks/result_scenario_3.json";
import { claimedBrand, maskLinks, minutesAfter, redactedText } from "./present";
import type { AgentResult, Campaign, InboxItem, Metrics, PrivacyView, ResultPoll, TrailEntry } from "./types";

const clone = <T>(value: T): T => structuredClone(value);

export const mockInbox = () => clone(inboxJson as InboxItem[]);
export const mockPrivacy = () => clone(privacyJson as PrivacyView);
export const mockCampaigns = () => clone(campaignsJson as Campaign[]);
export const mockMetrics = () => clone(metricsJson as Metrics);

const results = {
  scenario1: resultScenario1Json,
  scenario2: resultScenario2Json,
  scenario3: resultScenario3Json,
  legit: resultLegitJson,
} as const;
export type ResultFixture = keyof typeof results;

export const mockResult = (name: ResultFixture) => clone(results[name] as ResultPoll);

/** Mirrors the mock backend's routing of the seeded inbox to result fixtures. */
export const resultFixtureFor: Record<string, ResultFixture> = {
  msg_0001: "scenario1",
  msg_0003: "scenario3",
  msg_0101: "legit",
};

/** A poll caught mid-check: the first `steps` trail entries, no result yet. */
export function runningPoll(name: ResultFixture, steps: number): ResultPoll {
  const full = mockResult(name);
  return { ...full, status: "running", trail: full.trail.slice(0, steps), result: null, was_this_you_items: [] };
}

export type GalleryVerdict = "unsure" | "mixed";

/**
 * Gallery specimens for the two verdicts the mock files don't carry.
 * Built from scenario 1's poll, with the verdict, reason and evidence replaced.
 * These are display fixtures only. The live screens still poll the mock API.
 */
export function galleryVerdict(variant: GalleryVerdict): ResultPoll {
  const poll = mockResult("scenario1");
  const result = poll.result as AgentResult;
  const shared = {
    verdict: "unsure" as const,
    confidence_words: "not sure" as const,
    actions: ["open_official_app", "call_number_on_card"] as AgentResult["actions"],
    was_this_you: [] as string[],
    replan: false,
  };
  if (variant === "mixed") {
    poll.result = {
      ...result,
      ...shared,
      reason: "Some signs point to a scam, but we couldn't confirm it.",
      evidence: [
        { tool: "check_link", finding: "The link looks like an official domain" },
        { tool: "check_sender", finding: "The sender does not match a known official channel" },
      ],
    };
  } else {
    poll.result = {
      ...result,
      ...shared,
      reason: "We couldn’t confirm who sent this text.",
      evidence: [
        { tool: "check_sender", finding: "The sender could not be confirmed" },
        { tool: "check_link", finding: "No link was available to check" },
      ],
    };
  }
  const verdictStep: TrailEntry = {
    step: poll.trail.length + 1,
    kind: "verdict",
    why: poll.result.reason,
    finding: "We’re not sure",
    ms: 0,
    at: poll.trail.at(-1)?.at ?? result.evidence[0]?.finding ?? "",
  };
  poll.trail = [
    ...poll.trail.filter((entry) => entry.kind !== "verdict"),
    verdictStep,
  ];
  return poll;
}

/** Redacted message text for a gallery bubble. Links in the raw text become a chip. */
export function galleryMessage(messageId: string): { text: string; claimedBrand?: string | null } {
  const item = mockInbox().find((row) => row.message_id === messageId);
  const privacy = messageId === mockPrivacy().message_id ? mockPrivacy() : undefined;
  const campaign = mockCampaigns().find((row) => row.linked_message_ids.includes(messageId));
  return {
    text: (privacy && redactedText(privacy)) || maskLinks(item?.text ?? ""),
    claimedBrand: campaign?.claimed_brand ?? (privacy ? claimedBrand(privacy) : undefined),
  };
}

/** The seeded inbox after every check has finished. */
export function checkedInbox(): InboxItem[] {
  return mockInbox().map((item) => {
    const fixture = resultFixtureFor[item.message_id];
    const result = fixture ? mockResult(fixture).result : null;
    return result
      ? { ...item, status: "done", verdict: result.verdict, confidence_words: result.confidence_words }
      : item;
  });
}

/** Scenario 2 after the customer taps "I clicked": the recovery poll and its first "Was this you?" item. */
export function recoverySpecimen() {
  const poll = mockResult("scenario2");
  const item = poll.was_this_you_items[0];
  const message = mockInbox().find((row) => row.message_id === poll.message_id);
  return { poll, item, minutesAfterMessage: minutesAfter(message?.received_at, item?.at) };
}
