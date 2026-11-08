import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockInbox, mockResult, recoverySpecimen } from "../fixtures";
import type { ResultPoll } from "../types";
import Recovery, { RecoveryView } from "./Recovery";

vi.mock("../api", async (importOriginal) => ({
  // Real ApiError and failureOf; only the network calls are mocked.
  ...(await importOriginal<typeof import("../api")>()),
  getInbox: vi.fn(),
  postClicked: vi.fn(),
  confirmTransaction: vi.fn(),
  pollResult: vi.fn(),
  getHealth: vi.fn(() => Promise.reject(new Error("no health in tests"))),
}));
const api = vi.mocked(await import("../api"));

function renderRecovery() {
  return render(
    <MemoryRouter initialEntries={["/recovery/msg_0001"]}>
      <Routes>
        <Route path="/recovery/:messageId" element={<Recovery />} />
        <Route path="/consent" element={<p>Consent screen</p>} />
        <Route path="/inbox" element={<p>Inbox screen</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RecoveryView", () => {
  it("shows a 'Was this you?' card with the amount, payee and time after the text", () => {
    const spec = recoverySpecimen();
    render(
      <MemoryRouter>
        <RecoveryView stage="transfer" {...spec} />
      </MemoryRouter>,
    );
    expect(spec.minutesAfterMessage).toBe(17);
    expect(screen.getByText("$900")).toBeInTheDocument();
    expect(screen.getByText("Unknown Payee")).toBeInTheDocument();
    expect(screen.getByText("Today, 9:31 AM")).toBeInTheDocument();
    expect(screen.getByText("17 minutes after the text")).toBeInTheDocument();
    expect(screen.getByText("Was this you?")).toBeInTheDocument();
  });

  it("builds the checklist from the recovery actions, with no percentages or contact details", () => {
    const { container } = render(
      <MemoryRouter>
        <RecoveryView stage="checklist" poll={mockResult("scenario2")} />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    expect(screen.getByText("Review your card controls")).toBeInTheDocument();
    expect(screen.getByText("Change your bank password")).toBeInTheDocument();
    expect(screen.getByText("Contact your bank")).toBeInTheDocument();
    expect(screen.getByText(/0 of 3 marked complete/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d\s?%|https?:|\d{3}[\s.-]\d{3}[\s.-]\d{4}|your account is fine/i);
  });
});

describe("RecoveryView with a flagged purchase (the live Nessie seed plants the $900 as a purchase)", () => {
  it("names the purchase on the card and in the checklist banner", () => {
    const spec = recoverySpecimen();
    const purchase = { ...spec.item!, type: "purchase" as const };
    const { rerender } = render(
      <MemoryRouter>
        <RecoveryView stage="transfer" {...spec} item={purchase} />
      </MemoryRouter>,
    );
    expect(screen.getByText("A new purchase after the text.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Yes, I made this purchase/ })).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <RecoveryView stage="checklist" poll={spec.poll} activityNoun="purchase" />
      </MemoryRouter>,
    );
    expect(screen.getByText("If the purchase wasn’t yours, contact your bank promptly.")).toBeInTheDocument();
  });
});

describe("Recovery on the mock API", () => {
  let update: (poll: ResultPoll) => void;

  beforeEach(() => {
    sessionStorage.clear();
    api.getInbox.mockResolvedValue(mockInbox());
    api.postClicked.mockResolvedValue({ message_id: "msg_0001", status: "queued", mode: "recovery" });
    api.confirmTransaction.mockResolvedValue({ ref: "txn_3", was_me: false, recorded: true });
    api.pollResult.mockImplementation((_id, onUpdate) => {
      update = onUpdate;
      return () => undefined;
    });
  });
  afterEach(() => vi.clearAllMocks());

  it("waits for each tap: I clicked, then Was this you?, then the checklist", async () => {
    renderRecovery();
    const start = await screen.findByRole("button", { name: /I clicked and entered my info/ });
    expect(api.postClicked).not.toHaveBeenCalled();
    expect(api.pollResult).not.toHaveBeenCalled();

    fireEvent.click(start);
    expect(await screen.findByText("Checking activity since the text…")).toBeInTheDocument();
    expect(api.postClicked).toHaveBeenCalledWith("msg_0001");

    // A stale check-mode result is not the recovery answer.
    act(() => update(mockResult("scenario1")));
    expect(screen.getByText("Checking activity since the text…")).toBeInTheDocument();

    act(() => update(mockResult("scenario2")));
    expect(await screen.findByText("$900")).toBeInTheDocument();
    expect(await screen.findByText("17 minutes after the text")).toBeInTheDocument();
    expect(api.confirmTransaction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /No, I don’t recognize this/ }));
    expect(await screen.findByText("You’re in control.")).toBeInTheDocument();
    expect(api.confirmTransaction).toHaveBeenCalledWith("txn_3", false);
    expect(screen.getByText("If the transfer wasn’t yours, contact your bank promptly.")).toBeInTheDocument();

    for (const box of screen.getAllByRole("checkbox")) fireEvent.click(box);
    expect(screen.getByText("You’ve taken the next steps.")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 marked complete/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Return to messages/ }));
    expect(await screen.findByText("Inbox screen")).toBeInTheDocument();
  });

  it("notes a recognized transfer", async () => {
    api.confirmTransaction.mockResolvedValue({ ref: "txn_3", was_me: true, recorded: true });
    renderRecovery();
    fireEvent.click(await screen.findByRole("button", { name: /I clicked and entered my info/ }));
    await screen.findByText("Checking activity since the text…");
    act(() => update(mockResult("scenario2")));
    fireEvent.click(await screen.findByRole("button", { name: /Yes, I made this transfer/ }));
    expect(await screen.findByText("Activity marked as recognized in this demo.")).toBeInTheDocument();
    expect(api.confirmTransaction).toHaveBeenCalledWith("txn_3", true);
  });

  it("goes straight to the checklist for 'I only opened the link', without starting a check", async () => {
    renderRecovery();
    fireEvent.click(await screen.findByRole("button", { name: /I only opened the link/ }));
    expect(screen.getByText("You’re in control.")).toBeInTheDocument();
    expect(api.postClicked).not.toHaveBeenCalled();
  });

  it("asks to link an account first when the customer skipped linking", async () => {
    sessionStorage.setItem("sentinel-linked", "false");
    renderRecovery();
    fireEvent.click(await screen.findByRole("button", { name: /Link an account to check activity/ }));
    expect(await screen.findByText("Consent screen")).toBeInTheDocument();
    expect(api.postClicked).not.toHaveBeenCalled();
  });

  it("says nothing was changed when the tap doesn't go through", async () => {
    api.postClicked.mockRejectedValue(new Error("offline"));
    renderRecovery();
    fireEvent.click(await screen.findByRole("button", { name: /I clicked and entered my info/ }));
    expect(await screen.findByText(/Nothing was changed/)).toBeInTheDocument();
    expect(api.pollResult).not.toHaveBeenCalled();
  });
});
