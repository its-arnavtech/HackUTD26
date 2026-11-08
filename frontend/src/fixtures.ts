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
import type { Campaign, InboxItem, Metrics, PrivacyView, ResultPoll } from "./types";

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
