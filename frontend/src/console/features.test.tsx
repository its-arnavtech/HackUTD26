import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("L15 features", () => {
  it("agent accuracy page shows the measured numbers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/agent-metrics")
          return json({
            generated_at: "2026-11-08T15:00:00Z", model: "nvidia/nemotron-3.5-bolt-e4b", dataset: "held out", n: 45, errors: 0, per_category: 5,
            accuracy: 0.8, unsure: 0.1, scams_caught: 0.85, false_alarms: 0.2, avg_seconds: 9.1, worst_seconds: 20, avg_tool_calls: 3.2,
            tool_use: { check_link: 0.9 }, categories: [{ category: "billing_scam", n: 5, correct: 0.8, unsure: 0.2, wrong: 0 }],
          });
        return json({ status: "ok", mocked_routes: {} });
      }),
    );
    const { AgentAccuracyPage } = await import("./features");
    render(<MemoryRouter><AgentAccuracyPage /></MemoryRouter>);
    expect((await screen.findAllByText("80%")).length).toBeGreaterThan(0);
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("Fake billing")).toBeInTheDocument();
  });

  it("trusted contact is offered only after a scam verdict and alerts only on tap", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url === "/api/trusted-contact") return json({ contact: { name: "Maya", phone_masked: "•••• 4471" } });
        if (url === "/api/actions") return json({ note: "Simulated for the demo. We'd text Maya (•••• 4471)" });
        return json({});
      }),
    );
    const { TrustedContactCard } = await import("./features");
    const message = { message_id: "m1", sender: "x", text: "t", received_at: "2026-11-08T15:00:00Z", status: "done" as const, source: "authored" as const };
    const done = (verdict: "likely_scam" | "likely_safe") => ({
      message_id: "m1", status: "done" as const, mode: "check" as const, trail: [], was_this_you_items: [],
      result: { plan: [], verdict, confidence_words: "likely" as const, reason: "r", evidence: [], actions: [], was_this_you: [], replan: false },
    });
    const { rerender } = render(<TrustedContactCard message={message} poll={done("likely_safe")} />);
    await waitFor(() => expect(calls).toContain("GET /api/trusted-contact"));
    expect(screen.queryByText(/Tell Maya/)).not.toBeInTheDocument();
    rerender(<TrustedContactCard message={message} poll={done("likely_scam")} />);
    const button = await screen.findByRole("button", { name: /Tell Maya/ });
    expect(calls.some((c) => c.includes("/api/actions"))).toBe(false);
    fireEvent.click(button);
    expect(await screen.findByText(/We'd text Maya/)).toBeInTheDocument();
  });
});
