import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Gallery, { galleryItems } from "./Gallery";

describe("/gallery", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders every phone state from the mocks without touching the network", () => {
    const fetchSpy = vi.fn(() => Promise.reject(new Error("the gallery must not fetch")));
    vi.stubGlobal("fetch", fetchSpy);
    render(
      <MemoryRouter initialEntries={["/gallery"]}>
        <Gallery />
      </MemoryRouter>,
    );
    for (const item of galleryItems) {
      expect(screen.getByRole("region", { name: item.label })).toBeInTheDocument();
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("keeps percentages out of every phone screen", () => {
    render(
      <MemoryRouter initialEntries={["/gallery"]}>
        <Gallery />
      </MemoryRouter>,
    );
    for (const item of galleryItems) {
      expect(screen.getByRole("region", { name: item.label }).textContent).not.toMatch(/\d\s?%/);
    }
  });

  it("shows the checking state held mid-check", () => {
    render(
      <MemoryRouter initialEntries={["/gallery?group=start"]}>
        <Gallery />
      </MemoryRouter>,
    );
    const checking = screen.getByRole("region", { name: "03 · Checking" });
    expect(within(checking).getByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "04 · Very likely a scam" })).not.toBeInTheDocument();
  });
});
