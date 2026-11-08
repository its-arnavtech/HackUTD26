import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import realMetricsJson from "../../../eval/metrics.json";
import { checkedInbox, mockCampaigns, mockMetrics } from "../fixtures";
import { isLinked } from "../linking";
import type { Metrics } from "../types";
import AccuracyPage, { AccuracyView, oursMatchesBaseline } from "./AccuracyPage";
import CampaignView, { CampaignListView } from "./CampaignView";
import Consent from "./Consent";

vi.mock("../api", () => ({ getCampaigns: vi.fn(), getInbox: vi.fn(), getMetrics: vi.fn() }));
const api = vi.mocked(await import("../api"));

/** A13's real output (L7 classifier): nine taxonomy categories including `legit`, and no agent sample yet. */
const realMetrics = () => structuredClone(realMetricsJson as Metrics);

function inRouter(ui: ReactNode, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path} element={ui} />
        <Route path="/inbox" element={<p>Inbox screen</p>} />
        <Route path="/result/:id" element={<p>Result screen</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.clearAllMocks());

describe("Consent", () => {
  it("links only after a tap, then continues to messages", async () => {
    sessionStorage.setItem("sentinel-linked", "false");
    inRouter(<Consent />);
    expect(screen.getByText(/Read recent activity and bill status/)).toBeInTheDocument();
    expect(screen.getByText(/Bank records stay in this session/)).toBeInTheDocument();
    expect(isLinked()).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Link Capital One/ }));
    expect(screen.getByText("Capital One linked for this demo.")).toBeInTheDocument();
    expect(isLinked()).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Continue to messages/ }));
    expect(await screen.findByText("Inbox screen")).toBeInTheDocument();
  });

  it("lets the customer skip linking", async () => {
    inRouter(<Consent />);
    fireEvent.click(screen.getByRole("button", { name: /Continue without linking/ }));
    expect(await screen.findByText("Inbox screen")).toBeInTheDocument();
    expect(isLinked()).toBe(false);
  });
});

describe("Campaign view", () => {
  it("shows the count today and first seen, then the redacted template and linked messages on tap", () => {
    const onOpen = vi.fn();
    const onToggle = vi.fn();
    const { rerender, container } = render(
      <MemoryRouter>
        <CampaignListView campaigns={mockCampaigns()} inbox={checkedInbox()} onToggle={onToggle} onOpenMessage={onOpen} />
      </MemoryRouter>,
    );
    expect(screen.getByText("140")).toBeInTheDocument();
    expect(screen.getByText("First seen November 5 · Anonymized patterns")).toBeInTheDocument();
    expect(screen.queryByText("The shared pattern")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /View the pattern/ })[0]);
    expect(onToggle).toHaveBeenCalledWith("camp_07");

    rerender(
      <MemoryRouter>
        <CampaignListView campaigns={mockCampaigns()} inbox={checkedInbox()} expanded={["camp_07"]} onOpenMessage={onOpen} />
      </MemoryRouter>,
    );
    expect(screen.getByText("<AMOUNT>")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /T-Mobile: your bill is overdue/ }));
    expect(onOpen).toHaveBeenCalledWith("msg_0003");
    expect(container.textContent).not.toMatch(/\d\s?%|https?:|tmobile-\*/);
  });

  it("has an empty state", () => {
    render(
      <MemoryRouter>
        <CampaignListView campaigns={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("No patterns to show yet.")).toBeInTheDocument();
  });

  it("loads campaigns through the API and opens a linked message's check", async () => {
    api.getCampaigns.mockResolvedValue(mockCampaigns());
    api.getInbox.mockResolvedValue(checkedInbox());
    inRouter(<CampaignView />, "/campaigns");
    fireEvent.click((await screen.findAllByRole("button", { name: /View the pattern/ }))[1]);
    fireEvent.click(await screen.findByRole("button", { name: /Capital One Alert/ }));
    expect(await screen.findByText("Result screen")).toBeInTheDocument();
  });
});

describe("Accuracy page", () => {
  it("reads the real eval/metrics.json shape: every category, FPR and redaction cost", () => {
    const metrics = realMetrics();
    render(<AccuracyView metrics={metrics} />);
    const table = screen.getByRole("table");
    for (const label of ["Bank impersonation", "Fake delivery", "Conversation lure", "Legitimate messages"]) {
      expect(within(table).getByText(label)).toBeInTheDocument();
    }
    expect(within(table).getAllByRole("row")).toHaveLength(2 + metrics.categories.length);
    expect(screen.getByText("16.0%")).toBeInTheDocument();
    expect(screen.getByText("11.3%")).toBeInTheDocument();
    expect(screen.getByText("0.90")).toBeInTheDocument();
    expect(screen.getByText("0.88")).toBeInTheDocument();
    expect(screen.getByText("Macro F1 · baseline 0.79 · SentinelAI 0.88")).toBeInTheDocument();
    expect(screen.getByText("Measured on the held-out test split.")).toBeInTheDocument();
    expect(screen.getByText("388 messages · Test split only")).toBeInTheDocument();
    expect(screen.getByText(/full-agent sample hasn’t been run yet/)).toBeInTheDocument();
  });

  it("says so when SentinelAI's column is only the baseline stand-in", () => {
    const standIn = realMetrics();
    standIn.macro_f1.ours = standIn.macro_f1.baseline;
    standIn.false_positive_rate.ours = standIn.false_positive_rate.baseline;
    for (const row of standIn.categories) row.ours = { ...row.baseline };
    expect(oursMatchesBaseline(realMetrics())).toBe(false);
    expect(oursMatchesBaseline(mockMetrics())).toBe(false);
    expect(oursMatchesBaseline(standIn)).toBe(true);
    render(<AccuracyView metrics={standIn} />);
    expect(screen.getByText("SentinelAI’s classifier is still the baseline stand-in.")).toBeInTheDocument();
  });

  it("switches to the public SMS set and says plainly where SentinelAI falls short", () => {
    render(<AccuracyView metrics={realMetrics()} />);
    fireEvent.click(screen.getByRole("button", { name: "Public SMS" }));
    expect(screen.getByText("ucirvine/sms_spam")).toBeInTheDocument();
    expect(screen.getByText("5574 messages · Test split only")).toBeInTheDocument();
    const table = within(screen.getByRole("table"));
    for (const value of ["17.7%", "9.0%", "3.4%", "2.9%"]) expect(table.getByText(value)).toBeInTheDocument();
    expect(screen.getByText(/catches fewer spam texts than the simple baseline \(9.0% vs 17.7%\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Held-out synthetic" }));
    expect(screen.queryByText(/catches fewer spam texts/)).not.toBeInTheDocument();
  });

  it("shows the agent sample when there is one, and labels the mock as illustrative", () => {
    render(<AccuracyView metrics={mockMetrics()} illustrative />);
    expect(screen.getByText("Illustrative data. Not measured model performance.")).toBeInTheDocument();
    expect(screen.getByText(/sample of 50 messages.*88.0% were correct and 8.0% came back/)).toBeInTheDocument();
  });

  it("disables the public tab when there is no public set, and shows no numbers on error", async () => {
    const metrics = { ...realMetrics(), public_set: null };
    const { unmount } = render(<AccuracyView metrics={metrics} />);
    expect(screen.getByRole("button", { name: "Public SMS" })).toBeDisabled();
    unmount();
    api.getMetrics.mockRejectedValue(new Error("offline"));
    render(<AccuracyPage />);
    expect(await screen.findByText("The evaluation results couldn’t be loaded.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
