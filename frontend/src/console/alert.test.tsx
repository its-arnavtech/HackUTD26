import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { PrivacyView, ResultPoll } from "../types";
import { IncomingAlert, LinkSenderPanel } from "./protection";

const done = (verdict: "likely_scam" | "unsure" | "likely_safe"): ResultPoll => ({
  message_id: "m1", status: "done", mode: "check", trail: [], was_this_you_items: [],
  result: { plan: [], verdict, confidence_words: "likely", reason: "The link imitates PayPal.", evidence: [], actions: [], was_this_you: [], replan: false },
});

const privacy = (toolResults: unknown[]): PrivacyView => ({
  message_id: "m1",
  redaction: { counts: {} as never, kept: [] },
  recipients: [{ recipient: "nemotron", kind: "model", received_fields: [], payload: { tool_results: toolResults } }],
  never_sent: [],
});

describe("L15d link/sender panel and incoming alert", () => {
  it("shows what the link check found as plain text, never a clickable link, with a spoofing warning", () => {
    const { container } = render(
      <LinkSenderPanel
        poll={done("likely_scam")}
        privacy={privacy([
          { ok: true, tool: "check_link", result: { domain: "paypal-claims-center.com", lookalike_of: "paypal.com", signals: ["PayPal brand term in a domain PayPal doesn't own"] } },
          { ok: true, tool: "check_sender", result: { matches_official_channel: false, official_channels_known: false } },
        ])}
      />,
    );
    expect(screen.getByText("paypal-claims-center.com")).toBeInTheDocument();
    expect(screen.getByText("paypal.com")).toBeInTheDocument();
    expect(container.querySelector("a")).toBeNull(); // nothing clickable
    expect(screen.getByText(/can be faked/)).toBeInTheDocument();
    expect(screen.getByText(/does not publish its texting numbers/)).toBeInTheDocument();
  });

  it("says a link could not be checked instead of calling it safe", () => {
    render(<LinkSenderPanel poll={done("unsure")} privacy={privacy([{ ok: false, tool: "check_link" }])} />);
    expect(screen.getByText(/could not be checked/)).toBeInTheDocument();
  });

  it("incoming alert shows checking, then the verdict headline, and its buttons work", () => {
    const onView = vi.fn();
    const onDismiss = vi.fn();
    const { rerender } = render(<IncomingAlert poll={undefined} onView={onView} onDismiss={onDismiss} />);
    expect(screen.getByText(/Checking it now/)).toBeInTheDocument();
    rerender(<IncomingAlert poll={done("likely_scam")} onView={onView} onDismiss={onDismiss} />);
    expect(screen.getByText("Potential scam detected")).toBeInTheDocument();
    expect(screen.getByText(/simulated incoming text/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /See why/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onView).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
