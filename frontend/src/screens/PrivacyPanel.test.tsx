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

  it("renders A3's lowercase hex phone tags as chips, not raw text", () => {
    const view = mockPrivacy();
    const tagged = "Hi <PERSON>, call <PHONE_HASH_2ae6f01c9b3d4e57> or <PHONE_HASH_2ae6…> about <URL_1>.";
    for (const r of view.recipients) if ("text_redacted" in r.payload) r.payload = { ...r.payload, text_redacted: tagged };
    const { container } = render(<PrivacyView view={view} />);
    const chips = [...container.querySelectorAll(".redacted-message .privacy-chip")].map((chip) => chip.textContent);
    expect(chips).toEqual(["<PERSON>", "<PHONE_HASH_2ae6f01c9b3d4e57>", "<PHONE_HASH_2ae6…>", "<URL_1>"]);
  });
});
