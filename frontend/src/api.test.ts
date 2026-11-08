import { afterEach, describe, expect, it, vi } from "vitest";
import { pollResult } from "./api";
import type { ResultPoll } from "./types";

const running = { status: "running", trail: [] } as unknown as ResultPoll;
const done = { status: "done", trail: [] } as unknown as ResultPoll;

function respondWith(...polls: ResultPoll[]) {
  const fetchMock = vi.fn();
  for (const poll of polls) fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(poll)));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("pollResult", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("polls every interval until the result is done", async () => {
    vi.useFakeTimers();
    const fetchMock = respondWith(running, running, done);
    const seen: string[] = [];
    pollResult("msg_1", (poll) => seen.push(poll.status), undefined, 1000);

    await vi.advanceTimersByTimeAsync(5000);
    expect(seen).toEqual(["running", "running", "done"]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/messages/msg_1/result");
  });

  it("stops when cancelled", async () => {
    vi.useFakeTimers();
    const fetchMock = respondWith(running, running, done);
    const stop = pollResult("msg_1", () => undefined, undefined, 1000);
    await vi.advanceTimersByTimeAsync(0);
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
