import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AlertStatus } from "./api";
import { alertMessage, TrustedAlertConsole, TrustedAlertPhone } from "./trustedAlert";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  postAlertAction: vi.fn(),
  getAlertStatus: vi.fn(),
}));
const api = vi.mocked(await import("./api"));

const status = (over: Partial<AlertStatus> = {}): AlertStatus => ({
  message_id: "msg_0002",
  state: "done",
  call_outcome: null,
  email_sent: false,
  simulated: false,
  called_at: null,
  email_sent_at: null,
  alert_text: "Hi, it's your SentinelAI contact alert. Please call them when you can.",
  detail: null,
  ...over,
});

const actionReply = (alert: AlertStatus) => ({
  message_id: alert.message_id,
  action: "alert_trusted_contact" as const,
  status: "simulated" as const,
  note: "Alert started.",
  alert,
});

/** Let pending promises settle, then move the fake clock. */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("alertMessage", () => {
  it.each([
    [status({ state: "calling" }), "Calling your trusted contact…", false],
    [status({ call_outcome: "answered" }), "They picked up.", false],
    [status({ call_outcome: "voicemail", email_sent: true }), "They didn’t pick up. We left a voicemail and emailed them.", false],
    [status({ call_outcome: "no_answer", email_sent: true }), "They didn’t pick up. We emailed them.", false],
    [status({ call_outcome: "failed", email_sent: true }), "We couldn’t call them, so we emailed them.", false],
    [status({ call_outcome: "voicemail" }), "We couldn’t reach them. Here’s what to tell them:", true],
    [status({ call_outcome: "no_answer" }), "We couldn’t reach them. Here’s what to tell them:", true],
    [status({ call_outcome: "failed" }), "We couldn’t reach them. Here’s what to tell them:", true],
  ])("reads %#", (s, line, showText) => {
    expect(alertMessage(s)).toEqual({ line, showText });
  });

  it("adds (simulated) when the backend simulated the call", () => {
    expect(alertMessage(status({ call_outcome: "answered", simulated: true })).line).toBe("They picked up. (simulated)");
    expect(alertMessage(status({ state: "calling", simulated: true })).line).toBe("Calling your trusted contact… (simulated)");
  });

  it("falls back to what to tell them when polling timed out mid-call", () => {
    expect(alertMessage(status({ state: "calling" }), true).showText).toBe(true);
  });
});

describe("trusted-contact alert polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    api.postAlertAction.mockReset();
    api.getAlertStatus.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls only on tap, polls every 2 s while calling, and stops when done", async () => {
    api.postAlertAction.mockResolvedValue(actionReply(status({ state: "calling" })));
    api.getAlertStatus
      .mockResolvedValueOnce(status({ state: "calling" }))
      .mockResolvedValueOnce(status({ call_outcome: "answered", called_at: "2026-11-08T16:00:00Z" }));
    render(<TrustedAlertPhone messageId="msg_0002" />);
    expect(api.postAlertAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Alert my trusted contact/ }));
    await advance(0);
    expect(api.postAlertAction).toHaveBeenCalledWith("msg_0002");
    expect(screen.getByText("Calling your trusted contact…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Alert my trusted contact/ })).toBeDisabled();

    await advance(1999);
    expect(api.getAlertStatus).not.toHaveBeenCalled();
    await advance(1);
    expect(api.getAlertStatus).toHaveBeenCalledTimes(1);
    await advance(2000);
    expect(api.getAlertStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByText("They picked up.")).toBeInTheDocument();

    await advance(10_000);
    expect(api.getAlertStatus).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Alert my trusted contact/ })).toBeEnabled();
  });

  it("stops polling after 120 seconds and shows what to tell them", async () => {
    api.postAlertAction.mockResolvedValue(actionReply(status({ state: "calling" })));
    api.getAlertStatus.mockResolvedValue(status({ state: "calling" }));
    render(<TrustedAlertPhone messageId="msg_0002" />);
    fireEvent.click(screen.getByRole("button", { name: /Alert my trusted contact/ }));
    await advance(0);

    for (let i = 0; i < 70; i += 1) await advance(2000);
    const polls = api.getAlertStatus.mock.calls.length;
    expect(polls).toBeGreaterThanOrEqual(58);
    expect(polls).toBeLessThanOrEqual(60);
    expect(screen.getByText(/We couldn’t reach them\. Here’s what to tell them:/)).toBeInTheDocument();

    await advance(30_000);
    expect(api.getAlertStatus).toHaveBeenCalledTimes(polls);
  });

  it("shows the voicemail-and-email outcome with (simulated) in the console", async () => {
    api.postAlertAction.mockResolvedValue(
      actionReply(status({ call_outcome: "voicemail", email_sent: true, simulated: true })),
    );
    render(<TrustedAlertConsole messageId="msg_0002" />);
    fireEvent.click(screen.getByRole("button", { name: /Alert my trusted contact/ }));
    await advance(0);
    expect(screen.getByText("They didn’t pick up. We left a voicemail and emailed them. (simulated)")).toBeInTheDocument();
    await advance(10_000);
    expect(api.getAlertStatus).not.toHaveBeenCalled();
  });

  it.each([
    ["no_answer", "They didn’t pick up. We emailed them."],
    ["failed", "We couldn’t call them, so we emailed them."],
  ] as const)("console shows %s with email sent", async (outcome, line) => {
    api.postAlertAction.mockResolvedValue(actionReply(status({ state: "calling" })));
    api.getAlertStatus.mockResolvedValue(status({ call_outcome: outcome, email_sent: true }));
    render(<TrustedAlertConsole messageId="msg_0002" />);
    fireEvent.click(screen.getByRole("button", { name: /Alert my trusted contact/ }));
    await advance(0);
    await advance(2000);
    expect(screen.getByText(line)).toBeInTheDocument();
  });

  it("shows alert_text as plain text, never a link", async () => {
    api.postAlertAction.mockResolvedValue(
      actionReply(status({ call_outcome: "no_answer", alert_text: "Please check in. Details: https://evil.example/x" })),
    );
    const { container } = render(<TrustedAlertPhone messageId="msg_0002" />);
    fireEvent.click(screen.getByRole("button", { name: /Alert my trusted contact/ }));
    await advance(0);
    expect(screen.getByText(/Here’s what to tell them:/)).toBeInTheDocument();
    expect(screen.getByText(/Please check in\. Details: <URL_1>/)).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).not.toContain("evil.example");
  });

  it("says nothing was sent when the tap fails", async () => {
    api.postAlertAction.mockRejectedValue(new Error("boom"));
    render(<TrustedAlertConsole messageId="msg_0002" />);
    fireEvent.click(screen.getByRole("button", { name: /Alert my trusted contact/ }));
    await advance(0);
    expect(screen.getByText("That didn’t go through. Nothing was sent.")).toBeInTheDocument();
  });
});
