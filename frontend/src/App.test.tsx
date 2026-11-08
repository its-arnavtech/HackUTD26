import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./hooks", () => ({
  useHealth: () => undefined,
  useHealthState: () => ({ health: undefined, settled: true }),
}));
vi.mock("./screens/Inbox", () => ({ default: () => <h1>Inbox screen</h1> }));
vi.mock("./screens/ResultCard", () => ({ default: () => <h1>Result screen</h1> }));
vi.mock("./screens/HowWeChecked", () => ({ default: () => <h1>Evidence screen</h1> }));
vi.mock("./screens/PrivacyPanel", () => ({ default: () => <h1>Privacy screen</h1> }));
vi.mock("./screens/Recovery", () => ({ default: () => <h1>Recovery screen</h1> }));
vi.mock("./screens/Consent", () => ({ default: () => <h1>Connection screen</h1> }));
vi.mock("./screens/CampaignView", () => ({ default: () => <h1>Campaign screen</h1> }));
vi.mock("./screens/AccuracyPage", () => ({ default: () => <h1>Accuracy screen</h1> }));
vi.mock("./screens/Gallery", () => ({ default: () => <h1>Gallery screen</h1> }));

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});

describe("desk navigation", () => {
  it("keeps the selected message across the check, the evidence, privacy, and recovery", () => {
    render(
      <MemoryRouter initialEntries={["/result/msg_0003"]}>
        <App />
      </MemoryRouter>,
    );
    const nav = within(screen.getByRole("navigation", { name: "Main navigation" }));
    expect(nav.getAllByRole("link")).toHaveLength(9);
    fireEvent.click(nav.getByRole("link", { name: "Evidence" }));
    expect(screen.getByRole("heading", { name: "Evidence screen" })).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy/msg_0003");
    fireEvent.click(nav.getByRole("link", { name: "Privacy" }));
    expect(screen.getByRole("heading", { name: "Privacy screen" })).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Recovery" })).toHaveAttribute("href", "/recovery/msg_0003");
    expect(nav.getByRole("link", { name: "Privacy" })).toHaveAttribute("aria-current", "page");
  });

  it("opens the compact menu, moves focus inside, and restores focus on Escape", () => {
    render(
      <MemoryRouter initialEntries={["/inbox"]}>
        <App />
      </MemoryRouter>,
    );
    const toggle = screen.getByRole("button", { name: "Open navigation" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const nav = within(screen.getByRole("navigation", { name: "Main navigation" }));
    expect(nav.getByRole("link", { name: "Messages" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    fireEvent.click(toggle);
    fireEvent.click(nav.getByRole("link", { name: "Accuracy" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("heading", { name: "Accuracy screen" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("reaches every desk, explains the three stages on the home page, and shows no demo badge", () => {
    render(
      <MemoryRouter initialEntries={["/inbox"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Names, account digits, and phone numbers/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is blocked, reported, or moved/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "a bill reminder that turns out to be paid" })).toHaveAttribute(
      "href",
      "/result/msg_0003",
    );
    const nav = within(screen.getByRole("navigation", { name: "Main navigation" }));
    for (const [label, heading] of [
      ["Patterns", "Campaign screen"],
      ["Gallery", "Gallery screen"],
      ["Connect", "Connection screen"],
      ["Recovery", "Recovery screen"],
      ["Messages", "Inbox screen"],
    ] as const) {
      fireEvent.click(nav.getByRole("link", { name: label }));
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.queryByText("Synthetic demo")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic data. No live account.")).toBeInTheDocument();
  });

  it("links the four views of the open message, marking the current one", () => {
    render(
      <MemoryRouter initialEntries={["/trail/msg_0003"]}>
        <App />
      </MemoryRouter>,
    );
    const folio = within(screen.getByRole("navigation", { name: "This message" }));
    expect(folio.getByRole("link", { name: "How we checked" })).toHaveAttribute("aria-current", "page");
    expect(folio.getByRole("link", { name: "If you clicked" })).toHaveAttribute("href", "/recovery/msg_0003");
    fireEvent.click(folio.getByRole("link", { name: "What we never saw" }));
    expect(screen.getByRole("heading", { name: "Privacy screen" })).toBeInTheDocument();
  });
});
