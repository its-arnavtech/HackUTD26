import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockPrivacy } from "../fixtures";
import { PrivacyView } from "./PrivacyPanel";

describe("PrivacyView", () => {
  it("shows the redacted message, the counts, and what each check received", () => {
    const view = mockPrivacy();
    const { container } = render(<PrivacyView view={view} />);
    expect(screen.getByText("<PERSON>")).toBeInTheDocument();
    expect(screen.getByText("1 name hidden")).toBeInTheDocument();
    expect(screen.getByText("Nemotron, the AI planner")).toBeInTheDocument();
    expect(screen.getByText("Link check")).toBeInTheDocument();
    expect(screen.getByText("Your name")).toBeInTheDocument();
    expect(screen.getByText("The sender's phone number")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/https?:\/\/|%\s|Linda/);
  });
});
