import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { checkedInbox, mockInbox, mockResult, runningPoll } from "../fixtures";
import { newestFirst } from "../hooks";
import type { ResultPoll } from "../types";
import Inbox, { InboxView, senderLabel } from "./Inbox";

vi.mock("../api", async (importOriginal) => ({
  // Real ApiError and failureOf; only the network calls are mocked.
  ...(await importOriginal<typeof import("../api")>()),
  getInbox: vi.fn(),
  postMessage: vi.fn(),
  pollResult: vi.fn(),
  getHealth: vi.fn(() => Promise.reject(new Error("no health in tests"))),
}));
const api = vi.mocked(await import("../api"));

describe("InboxView", () => {
  it("shows each finished check as a verdict in words, never a percentage", () => {
    const { container } = render(<InboxView items={newestFirst(checkedInbox())} />);
    expect(screen.getAllByText("Very likely a scam")).toHaveLength(2);
    expect(screen.getByText("Likely safe")).toBeInTheDocument();
    expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
  });

  it("lists the newest text first and formats the sender like a phone inbox", () => {
    render(<InboxView items={newestFirst(checkedInbox())} />);
    const rows = screen.getAllByRole("button");
    expect(within(rows[0]).getByText("(555) 019-2231")).toBeInTheDocument();
    expect(senderLabel("+15550104477")).toBe("(555) 010-4477");
    expect(senderLabel("CAPONE")).toBe("CAPONE");
  });

  it("shows Checking… and what the check is doing for an unfinished text", () => {
    const items = checkedInbox().map((item) =>
      item.message_id === "msg_0003" ? { ...item, status: "running" as const, verdict: null } : item,
    );
    render(<InboxView items={items} progress={{ msg_0003: runningPoll("scenario3", 1) }} />);
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(screen.getByText("Checking…").closest("button")).toBeDisabled();
    const plan = mockResult("scenario3").trail[0].finding!;
    expect(screen.getByText(plan)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Check a new demo text/ })).not.toBeInTheDocument();
  });

  it("opens a message on tap", () => {
    const onOpen = vi.fn();
    render(<InboxView items={newestFirst(checkedInbox())} onOpen={onOpen} />);
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(onOpen).toHaveBeenCalledWith("msg_0003");
  });

  it("offers a retry when messages can't load, without inventing a verdict", () => {
    const onRetry = vi.fn();
    render(<InboxView items={[]} state="error" onRetry={onRetry} />);
    expect(screen.getByText("We couldn’t load your messages.")).toBeInTheDocument();
    expect(screen.queryByText(/scam|safe|not sure/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Load messages again/ }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("Inbox on the mock API", () => {
  let updates: Map<string, (poll: ResultPoll) => void>;
  let stops: Map<string, ReturnType<typeof vi.fn>>;

  beforeEach(() => {
    updates = new Map();
    stops = new Map();
    api.getInbox.mockResolvedValue(mockInbox());
    api.pollResult.mockImplementation((id, onUpdate) => {
      updates.set(id, onUpdate);
      const stop = vi.fn();
      stops.set(id, stop);
      return stop;
    });
  });
  afterEach(() => vi.clearAllMocks());

  const renderInbox = () =>
    render(
      <MemoryRouter initialEntries={["/inbox"]}>
        <Routes>
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/result/:messageId" element={<p>Result page</p>} />
        </Routes>
      </MemoryRouter>,
    );

  it("polls only unfinished texts and swaps Checking… for the verdict when done", async () => {
    const view = renderInbox();
    expect(await screen.findAllByText("Checking…")).toHaveLength(2);
    expect([...updates.keys()].sort()).toEqual(["msg_0001", "msg_0003"]);

    act(() => updates.get("msg_0001")!(runningPoll("scenario1", 2)));
    expect(screen.getAllByText("Checking…")).toHaveLength(2);

    act(() => {
      updates.get("msg_0001")!(mockResult("scenario1"));
      updates.get("msg_0003")!(mockResult("scenario3"));
    });
    expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
    expect(screen.getAllByText("Very likely a scam")).toHaveLength(2);

    view.unmount();
    expect([...stops.values()].every((stop) => stop.mock.calls.length > 0)).toBe(true);
  });

  it("posts a synthetic demo text after a tap and starts checking it", async () => {
    api.getInbox.mockResolvedValueOnce(checkedInbox());
    api.postMessage.mockResolvedValue({ message_id: "msg_1000" });
    renderInbox();
    const button = await screen.findByRole("button", { name: /Check a new demo text/ });
    expect(api.postMessage).not.toHaveBeenCalled();

    api.getInbox.mockResolvedValueOnce([
      ...checkedInbox(),
      { ...mockInbox()[0], message_id: "msg_1000", received_at: "2026-11-08T11:00:00-06:00", source: "authored" },
    ]);
    fireEvent.click(button);
    expect(await screen.findByText("Checking…")).toBeInTheDocument();
    expect(api.postMessage).toHaveBeenCalledTimes(1);
    expect(updates.has("msg_1000")).toBe(true);
  });

  it("goes to the result for the tapped message", async () => {
    api.getInbox.mockResolvedValue(checkedInbox());
    renderInbox();
    fireEvent.click((await screen.findAllByRole("button"))[0]);
    expect(await screen.findByText("Result page")).toBeInTheDocument();
  });

  it("shows the error state when the inbox can't load", async () => {
    api.getInbox.mockRejectedValue(new Error("offline"));
    renderInbox();
    expect(await screen.findByText("We couldn’t load your messages.")).toBeInTheDocument();
  });
});
