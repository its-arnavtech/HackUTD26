import { describe, expect, it } from "vitest";
import { checkedInbox, mockInbox, mockResult, resultFixtureFor, runningPoll } from "./fixtures";

describe("mock fixtures", () => {
  it("has a result fixture for every seeded inbox message", () => {
    for (const item of mockInbox()) expect(resultFixtureFor[item.message_id]).toBeDefined();
  });

  it("returns independent copies so a screen can't mutate shared data", () => {
    const first = mockResult("scenario1");
    first.trail.length = 0;
    expect(mockResult("scenario1").trail.length).toBeGreaterThan(0);
  });

  it("finishes every inbox check with the verdict from its result", () => {
    for (const item of checkedInbox()) {
      expect(item.status).toBe("done");
      expect(item.verdict).toBe(mockResult(resultFixtureFor[item.message_id]).result?.verdict);
    }
  });

  it("holds a running poll without a result", () => {
    const poll = runningPoll("scenario1", 2);
    expect(poll.status).toBe("running");
    expect(poll.trail).toHaveLength(2);
    expect(poll.result).toBeNull();
  });
});
