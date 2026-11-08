import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { galleryMessage, galleryVerdict, mockInbox, mockPrivacy, mockResult, runningPoll } from "../fixtures";
import type { ResultPoll } from "../types";
import ResultCard, { ResultView } from "./ResultCard";

const scam = mockResult("scenario1");
const message = galleryMessage("msg_0001");

describe("ResultView", () => {
  it("shows the verdict, the confidence and the reason in words, with one primary action", () => {
    const onAction = vi.fn();
    const { container } = render(
      <MemoryRouter>
        <ResultView poll={scam} messageText={message.text} claimedBrand={message.claimedBrand} onAction={onAction} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Very likely a scam")).toBeInTheDocument();
    expect(screen.getByText(scam.result!.reason)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Block this sender/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /I clicked this link/ })).toHaveAttribute("href", "/recovery/msg_0001");
    expect(screen.getByText(/<PERSON>/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/%|https?:|your account is fine/i);
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Block this sender/ }));
    expect(onAction).toHaveBeenCalledWith("block_sender");
  });

  it("uses the mixed-evidence sentence and keeps the billing result on the official app", () => {
    const mixed = galleryVerdict("mixed");
    const { rerender } = render(
      <MemoryRouter>
        <ResultView poll={mixed} messageText={message.text} />
      </MemoryRouter>,
    );
    expect(screen.getByText("We’re not sure")).toBeInTheDocument();
    expect(screen.getByText("Some signs point to a scam, but we couldn't confirm it.")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <ResultView poll={mockResult("scenario3")} messageText={galleryMessage("msg_0003").text} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: /Use the official app/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Block this sender/ })).not.toBeInTheDocument();
  });

  it("shows Checking… with no verdict while the poll is still running", () => {
    render(
      <MemoryRouter>
        <ResultView poll={runningPoll("scenario1", 1)} messageText={message.text} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Checking this message…")).toBeInTheDocument();
    expect(screen.queryByText(/scam|Likely safe/)).not.toBeInTheDocument();
  });
});

vi.mock("../api", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return { getInbox: vi.fn(), getPrivacy: vi.fn(), postAction: vi.fn(), pollResult: vi.fn(), ApiError };
});
const api = vi.mocked(await import("../api"));

describe("Result card on the mock API", () => {
  let update: (poll: ResultPoll) => void;

  beforeEach(() => {
    api.getInbox.mockResolvedValue(mockInbox());
    api.getPrivacy.mockResolvedValue(mockPrivacy());
    api.postAction.mockResolvedValue({
      message_id: "msg_0001",
      action: "block_sender",
      status: "simulated",
      note: "Simulated for the demo. Nothing was sent.",
    });
    api.pollResult.mockImplementation((_id, onUpdate) => {
      update = onUpdate;
      return () => undefined;
    });
  });
  afterEach(() => vi.clearAllMocks());

  it("polls until the verdict arrives, and posts the action only after a tap", async () => {
    render(
      <MemoryRouter initialEntries={["/result/msg_0001"]}>
        <Routes>
          <Route path="/result/:messageId" element={<ResultCard />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Checking this message…")).toBeInTheDocument();
    expect(api.postAction).not.toHaveBeenCalled();

    act(() => update(scam));
    fireEvent.click(await screen.findByRole("button", { name: /Block this sender/ }));
    expect(await screen.findByText("Sender blocked in this demo.")).toBeInTheDocument();
    expect(screen.getByText(/<PERSON>/)).toBeInTheDocument();
    expect(screen.queryByText(/Linda/)).not.toBeInTheDocument();
    expect(api.postAction).toHaveBeenCalledWith("msg_0001", "block_sender");
  });
});
