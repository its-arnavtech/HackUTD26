// A17: the screens on the real API client. `fetch` is stubbed with the backend's own response
// shapes (POC_MVP 7.1, errors.py), so api.ts, the hooks and the screens run unmocked.
import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiModeLine } from "./App";
import { ApiError, failureOf, getPrivacy, pollResult, type Health } from "./api";
import { checkedInbox, mockCampaigns, mockMetrics, mockPrivacy, mockResult, runningPoll } from "./fixtures";
import { forgetHealth, useResult } from "./hooks";
import AccuracyPage from "./screens/AccuracyPage";
import CampaignView from "./screens/CampaignView";
import HowWeChecked from "./screens/HowWeChecked";
import Inbox from "./screens/Inbox";
import PrivacyPanel from "./screens/PrivacyPanel";
import ResultCard from "./screens/ResultCard";

type Handler = (init?: RequestInit) => Response | Promise<Response>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** The backend's one error shape (`backend/app/errors.py`). */
const apiError = (status: number, code: string, message: string, details: Record<string, unknown> = {}) =>
  json({ detail: message, error: { code, message, details } }, status);

const notWired = (issue: string) => apiError(501, "not_implemented", `Not implemented yet: ${issue} wires it`, { issue });
const unknownMessage = () => apiError(404, "not_found", "Unknown message_id");

const health = (mocked: Record<string, boolean>): Health => ({
  status: "ok",
  demo_mode: "replay",
  use_mocks: Object.values(mocked).every(Boolean),
  mocked_routes: mocked,
});

let routes: Record<string, Handler>;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const key = `${init?.method ?? "GET"} ${String(input)}`;
  const handler = routes[key];
  if (!handler) return apiError(404, "not_found", `No stub for ${key}`);
  return handler(init);
});
const calls = (key: string) =>
  fetchMock.mock.calls.filter(([url, init]) => `${init?.method ?? "GET"} ${String(url)}` === key).length;

function at(path: string, pattern: string, ui: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={pattern} element={ui} />
        <Route path="/inbox" element={<p>Inbox screen</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  forgetHealth();
  routes = { "GET /api/health": () => json(health({ metrics: false, privacy: false })) };
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  fetchMock.mockClear();
});

describe("api.ts errors", () => {
  it("reads the backend's error shape: 501 names the issue that wires the route", async () => {
    routes["GET /api/privacy/msg_0001"] = () => notWired("L6");
    const err = await getPrivacy("msg_0001").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 501, code: "not_implemented", issue: "L6" });
    expect(failureOf(err)).toBe("not_wired");
  });

  it("tells not found and offline apart from other failures", async () => {
    routes["GET /api/privacy/msg_9999"] = unknownMessage;
    expect(failureOf(await getPrivacy("msg_9999").catch((e: unknown) => e))).toBe("not_found");
    routes["GET /api/privacy/msg_0001"] = () => Promise.reject(new TypeError("Failed to fetch"));
    const offline = await getPrivacy("msg_0001").catch((e: unknown) => e);
    expect(offline).toMatchObject({ status: 0 });
    expect(failureOf(offline)).toBe("offline");
    routes["GET /api/privacy/msg_0002"] = () => new Response("<html>Bad gateway</html>", { status: 502 });
    expect(failureOf(await getPrivacy("msg_0002").catch((e: unknown) => e))).toBe("error");
  });
});

describe("polling", () => {
  it("stops at done", async () => {
    vi.useFakeTimers();
    const polls = [runningPoll("scenario1", 1), runningPoll("scenario1", 2), mockResult("scenario1")];
    routes["GET /api/messages/msg_0001/result"] = () => json(polls.shift() ?? mockResult("scenario1"));
    const seen: string[] = [];
    pollResult("msg_0001", (poll) => seen.push(poll.status), undefined, 1000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(seen).toEqual(["running", "running", "done"]);
    expect(calls("GET /api/messages/msg_0001/result")).toBe(3);
  });

  it("gives up on a check that runs too long, then polls again on retry", async () => {
    routes["GET /api/messages/msg_0001/result"] = () => json(runningPoll("scenario1", 1));
    // Screens use the three-minute default; a zero budget makes the first unfinished poll "slow".
    function Slow() {
      const { failure, retry } = useResult("msg_0001", true, 0);
      return failure ? <button onClick={retry}>{failure}</button> : <p>polling</p>;
    }
    render(<Slow />);
    const button = await screen.findByRole("button", { name: "slow" });
    const before = calls("GET /api/messages/msg_0001/result");
    fireEvent.click(button);
    await waitFor(() => expect(calls("GET /api/messages/msg_0001/result")).toBeGreaterThan(before));
  });
});

describe("screens on the live API", () => {
  it("how we checked: an unknown message says so instead of spinning", async () => {
    routes["GET /api/messages/msg_0042/result"] = unknownMessage;
    at("/trail/msg_0042", "/trail/:messageId", <HowWeChecked />);
    expect(await screen.findByText("We couldn’t find this message.")).toBeInTheDocument();
  });

  it("result card: an unknown message says so and leads back to the inbox, with no retry", async () => {
    routes["GET /api/messages/msg_0042/result"] = unknownMessage;
    routes["GET /api/inbox"] = () => json([]);
    routes["GET /api/privacy/msg_0042"] = unknownMessage;
    at("/result/msg_0042", "/result/:messageId", <ResultCard />);
    expect(await screen.findByText("We couldn’t find this message.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Try the check again/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /Back to your messages/ }));
    expect(await screen.findByText("Inbox screen")).toBeInTheDocument();
  });

  it("result card: a dropped connection offers a retry that finds the verdict", async () => {
    let up = false;
    routes["GET /api/messages/msg_0001/result"] = () =>
      up ? json(mockResult("scenario1")) : Promise.reject(new TypeError("Failed to fetch"));
    routes["GET /api/inbox"] = () => json(checkedInbox());
    routes["GET /api/privacy/msg_0001"] = () => notWired("L6");
    at("/result/msg_0001", "/result/:messageId", <ResultCard />);
    expect(await screen.findByText("We can’t reach SentinelAI right now.", {}, { timeout: 4000 })).toBeInTheDocument();
    up = true;
    fireEvent.click(screen.getByRole("button", { name: /Try the check again/ }));
    expect(await screen.findByText("Very likely a scam")).toBeInTheDocument();
  });

  it("result card: an action route that isn't wired yet changes nothing and says so", async () => {
    routes["GET /api/messages/msg_0001/result"] = () => json(mockResult("scenario1"));
    routes["GET /api/inbox"] = () => json(checkedInbox());
    routes["GET /api/privacy/msg_0001"] = () => json(mockPrivacy());
    routes["POST /api/actions"] = () => notWired("L9");
    at("/result/msg_0001", "/result/:messageId", <ResultCard />);
    fireEvent.click(await screen.findByRole("button", { name: /Block this sender/ }));
    expect(await screen.findByText("This action isn’t connected yet in this demo. Nothing was changed.")).toBeInTheDocument();
  });

  it("inbox: a failed new text keeps the inbox and shows a notice", async () => {
    routes["GET /api/inbox"] = () => json(checkedInbox());
    routes["POST /api/messages"] = () => apiError(500, "internal_error", "boom");
    at("/inbox", "/inbox", <Inbox />);
    fireEvent.click(await screen.findByRole("button", { name: /Check a new demo text/ }));
    expect(await screen.findByText("That didn’t go through. No message was added. Please try again.")).toBeInTheDocument();
    expect(screen.getAllByText("Very likely a scam")).toHaveLength(2);
  });

  it("inbox: offline, then retry loads the messages", async () => {
    let up = false;
    routes["GET /api/inbox"] = () => (up ? json(checkedInbox()) : Promise.reject(new TypeError("Failed to fetch")));
    at("/inbox", "/inbox", <Inbox />);
    expect(await screen.findByText("We can’t reach SentinelAI right now.")).toBeInTheDocument();
    up = true;
    fireEvent.click(screen.getByRole("button", { name: /Load messages again/ }));
    expect(await screen.findByText("Likely safe")).toBeInTheDocument();
  });

  it("privacy panel: not connected yet, then retry shows the record", async () => {
    let wired = false;
    routes["GET /api/privacy/msg_0001"] = () => (wired ? json(mockPrivacy()) : notWired("L6"));
    at("/privacy/msg_0001", "/privacy/:messageId", <PrivacyPanel />);
    expect(await screen.findByText("This part isn’t connected yet.")).toBeInTheDocument();
    wired = true;
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findByText("1 name hidden")).toBeInTheDocument();
  });

  it("campaigns: loading, then not connected yet with a retry", async () => {
    let wired = false;
    routes["GET /api/inbox"] = () => json(checkedInbox());
    routes["GET /api/campaigns"] = () => (wired ? json(mockCampaigns()) : notWired("A12"));
    at("/campaigns", "/campaigns", <CampaignView />);
    expect(screen.getByText("Loading the patterns…")).toBeInTheDocument();
    expect(await screen.findByText("This part isn’t connected yet.")).toBeInTheDocument();
    wired = true;
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findByText("140")).toBeInTheDocument();
  });

  it("accuracy: labels the numbers illustrative while /api/metrics serves its mock", async () => {
    routes["GET /api/health"] = () => json(health({ metrics: true, privacy: true }));
    routes["GET /api/metrics"] = () => json(mockMetrics());
    render(<AccuracyPage />);
    expect(await screen.findByText("Illustrative data. Not measured model performance.")).toBeInTheDocument();
  });

  it("accuracy: says the live route isn't connected, shows no numbers, and retries", async () => {
    let wired = false;
    routes["GET /api/metrics"] = () => (wired ? json(mockMetrics()) : notWired("A13"));
    render(<AccuracyPage />);
    expect(await screen.findByText("The live evaluation route isn’t connected yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    wired = true;
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Try again" })));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Measured on the held-out test split.")).toBeInTheDocument();
  });
});

describe("stage note", () => {
  it("says whether the API serves mocks, real code, or a mix", () => {
    expect(apiModeLine(undefined)).toBeUndefined();
    expect(apiModeLine(health({ inbox: true, metrics: true }))).toBe("Mock API responses.");
    expect(apiModeLine(health({ inbox: false, metrics: false }))).toBe("Live API.");
    expect(apiModeLine(health({ inbox: false, metrics: true, privacy: true }))).toBe("Live API · 2 of 3 routes on mocks.");
  });
});
