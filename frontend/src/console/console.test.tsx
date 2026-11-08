import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { InboxItem, PrivacyView, ResultPoll } from "../types";
import { buildRows, classifierLine, elapsedSeconds, toolsUsed } from "./timeline";

const message: InboxItem = {
  message_id: "msg_0001",
  sender: "227898",
  text: "Capital One Alert: Linda, verify at https://capone-verify-alert.com",
  received_at: "2026-11-08T09:14:00Z",
  status: "running",
  source: "scenario",
};

const poll = (over: Partial<ResultPoll> = {}): ResultPoll => ({
  message_id: "msg_0001",
  status: "running",
  mode: "check",
  trail: [
    { step: 1, kind: "plan", finding: "Check the link, the sender, then bank activity", at: "2026-11-08T09:14:01Z" },
    { step: 2, kind: "tool", tool: "check_link", why: "It asks to verify", finding: "Site registered 3 days ago", ms: 412, at: "2026-11-08T09:14:03Z" },
    { step: 3, kind: "tool", tool: "nessie_recent_activity", finding: "No unusual activity", ms: 1800, at: "2026-11-08T09:14:06Z" },
  ],
  was_this_you_items: [],
  ...over,
});

const privacy: PrivacyView = {
  message_id: "msg_0001",
  redaction: { counts: { names: 1, phones: 0, account_digits: 0, addresses: 0, emails: 0, urls: 1 } as never, kept: [] },
  recipients: [
    { recipient: "nemotron", kind: "model", received_fields: ["text_redacted", "classifier"], payload: { text_redacted: "Capital One Alert: <PERSON>, verify at <URL_1>", classifier: { category: "bank_impersonation", score: 0.91 } } },
  ],
  never_sent: [],
};

describe("timeline (L14)", () => {
  it("shows received, redaction, classifier, each step and a working row while running", () => {
    const rows = buildRows(message, poll(), privacy);
    expect(rows.map((r) => r.kind)).toEqual(["received", "redacted", "classifier", "plan", "tool", "tool", "waiting"]);
    const redacted = rows.find((r) => r.kind === "redacted")!;
    expect(redacted.raw).toContain("Linda");
    expect(redacted.redacted).toContain("<PERSON>");
    expect(redacted.redacted).not.toContain("Linda");
    expect(rows.find((r) => r.tool === "nessie_recent_activity")!.service).toBe("Nessie (Capital One)");
    expect(rows.find((r) => r.tool === "check_link")!.meta).toBe("0.41 s");
    expect(classifierLine(privacy)).toBe("Bank impersonation · score 0.91");
  });

  it("drops the working row when done and reports elapsed time and tools used", () => {
    const done = poll({ status: "done" });
    expect(buildRows(message, done, privacy).some((r) => r.kind === "waiting")).toBe(false);
    expect(elapsedSeconds(done)).toBe("5.0 s");
    expect(toolsUsed(done)).toEqual(["check_link", "nessie_recent_activity"]);
  });

  it("labels a text that came in by SMS", () => {
    const rows = buildRows({ ...message, source: "sms", sender: "unknown" }, poll(), undefined);
    expect(rows[0].title).toBe("Text received by SMS");
    expect(rows[0].detail).toMatch(/Forwarded/);
  });
});

describe("console (L14)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  it("scenario 1 resets, then shows the customer view and the live steps; no action is posted without a tap", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url === "/api/health") return json({ status: "ok", demo_mode: "replay", use_mocks: true, auth_enabled: false, mocked_routes: { inbox: true } });
        if (url === "/api/inbox") return json([message]);
        if (url === "/api/demo/reset") return json({ ok: true, inbox_count: 1 });
        if (url.startsWith("/api/privacy/")) return json(privacy);
        if (url.endsWith("/result")) return json(poll({ status: "done", result: { plan: ["check_link"], verdict: "likely_scam", confidence_words: "very likely", reason: "It asks you to verify on a site made 3 days ago.", evidence: [], actions: ["block_sender"], was_this_you: [], replan: false } }));
        return json({});
      }),
    );
    const { default: Console } = await import("./Console");
    render(
      <MemoryRouter>
        <Console />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Scenario 1/ }));
    expect(await screen.findByRole("heading", { name: "Very likely a scam" })).toBeInTheDocument();
    expect(await screen.findByText("Site registered 3 days ago")).toBeInTheDocument();
    expect(screen.getByText("What the AI saw")).toBeInTheDocument();
    await waitFor(() => expect(calls).toContain("POST /api/demo/reset"));
    expect(calls.some((c) => c.includes("/api/actions"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Block this sender" }));
    await waitFor(() => expect(calls).toContain("POST /api/actions"));
  });
});
