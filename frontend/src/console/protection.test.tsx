import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextSteps, riskOf } from "./protection";

describe("L15c risk + next steps", () => {
  it("maps verdict and confidence to an honest risk level", () => {
    expect(riskOf("likely_scam", "very likely")).toBe("High");
    expect(riskOf("likely_scam", "likely")).toBe("Medium");
    expect(riskOf("unsure", "not sure")).toBe("Inconclusive");
    expect(riskOf("likely_safe", "likely")).toBe("Low");
    expect(riskOf(undefined)).toBeUndefined();
  });

  it("changes the checklist with what the customer did, and tracks progress", () => {
    const message = { message_id: "m1", sender: "x", text: "t", received_at: "2026-11-08T15:00:00Z", status: "done" as const, source: "authored" as const };
    const poll = {
      message_id: "m1", status: "done" as const, mode: "check" as const, trail: [], was_this_you_items: [],
      result: { plan: [], verdict: "likely_scam" as const, confidence_words: "likely" as const, reason: "r", evidence: [], actions: [], was_this_you: [], replan: false },
    };
    render(<NextSteps message={message} poll={poll} />);
    expect(screen.getByText("I have not tapped any link in it")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "I sent money" }));
    expect(screen.getByText(/stop, recall or dispute/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /secured the account/ }));
    expect(screen.getByText(/1 of 4 done/)).toBeInTheDocument();
  });
});
