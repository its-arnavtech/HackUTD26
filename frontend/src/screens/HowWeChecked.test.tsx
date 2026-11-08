import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockResult, runningPoll } from "../fixtures";
import { TrailView } from "./HowWeChecked";

describe("TrailView", () => {
  it("renders each arrived step, including why it ran", () => {
    const trail = mockResult("scenario1").trail;
    render(<TrailView trail={trail.slice(0, 2)} checking />);
    expect(screen.getByText(trail[0].finding!)).toBeInTheDocument();
    expect(screen.getByText(trail[1].finding!)).toBeInTheDocument();
    expect(screen.queryByText(trail[2].finding!)).not.toBeInTheDocument();
    expect(screen.getByText("Still checking. New steps appear here.")).toBeInTheDocument();
    expect(document.querySelectorAll(".trail-enter")).toHaveLength(2);
  });

  it("shows a step that arrives on a later poll", () => {
    const running = runningPoll("scenario1", 1);
    const { rerender } = render(<TrailView trail={running.trail} checking />);
    const next = runningPoll("scenario1", 2);
    rerender(<TrailView trail={next.trail} checking />);
    expect(screen.getByText(next.trail[1].finding!)).toBeInTheDocument();
  });

  it("keeps the recovery re-plan and the billing plan distinct", () => {
    const recovery = mockResult("scenario2").trail;
    const billing = mockResult("scenario3").trail;
    const { rerender } = render(<TrailView trail={recovery} checking={false} />);
    expect(screen.getByText("A new plan")).toBeInTheDocument();
    rerender(<TrailView trail={billing} checking={false} />);
    expect(screen.queryByText("A new plan")).not.toBeInTheDocument();
    expect(screen.getByText("Your bill")).toBeInTheDocument();
  });
});
