import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { EXAMPLES, ExampleButtons, SafetyCenterPage } from "./examples";

describe("L15e demo examples and Safety Center", () => {
  it("covers scams, a genuine message and an ambiguous one, all from real companies or plain senders", () => {
    const ids = EXAMPLES.map((e) => e.id);
    expect(ids).toEqual(["bank", "otp", "delivery", "investment", "legit", "ambiguous"]);
    expect(EXAMPLES.find((e) => e.id === "legit")?.truth?.is_scam).toBe(false);
    expect(EXAMPLES.find((e) => e.id === "ambiguous")?.truth).toBeUndefined();
    for (const e of EXAMPLES.filter((x) => x.truth?.is_scam)) {
      expect(e.text).toMatch(/^(Chase|Amazon|UPS|Wells Fargo)/);
    }
  });

  it("clicking an example hands that exact message to the check", () => {
    const onRun = vi.fn();
    render(<ExampleButtons busy={false} onRun={onRun} />);
    fireEvent.click(screen.getByRole("button", { name: "Fake delivery fee" }));
    expect(onRun).toHaveBeenCalledWith(EXAMPLES.find((e) => e.id === "delivery"));
  });

  it("Safety Center shows every topic with what to do if you already fell for it", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok", mocked_routes: {} }))));
    render(
      <MemoryRouter>
        <SafetyCenterPage />
      </MemoryRouter>,
    );
    for (const name of ["Bank impersonation", "One-time-code theft", "Fake delivery", "Investment scams", "Job scams", "Family emergency"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.getAllByText(/Already fell for it\?/)).toHaveLength(6);
    vi.unstubAllGlobals();
  });
});
