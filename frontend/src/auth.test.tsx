import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

type Handler = (url: string, init?: RequestInit) => Response;

function stubFetch(handler: Handler) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  document.cookie = "sa_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("api client with auth (L13)", () => {
  it("sends the CSRF cookie as a header on POST, never on GET", async () => {
    document.cookie = "sa_csrf=tok123";
    const fetchMock = stubFetch(() => json({ ok: true, message_id: "m", action: "block_sender", note: "" }));
    const api = await import("./api");
    await api.getInbox();
    await api.postAction("msg_1", "block_sender");
    const headers = (i: number) => fetchMock.mock.calls[i][1]?.headers as Record<string, string>;
    expect(headers(0)["X-CSRF-Token"]).toBeUndefined();
    expect(headers(1)["X-CSRF-Token"]).toBe("tok123");
    expect(fetchMock.mock.calls[1][1]?.credentials).toBe("same-origin");
  });

  it("adds no CSRF header when auth is off (no cookie)", async () => {
    const fetchMock = stubFetch(() => json({ message_id: "m" }));
    const api = await import("./api");
    await api.postClicked("msg_1");
    expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("refreshes once on 401 and retries the call", async () => {
    let inboxCalls = 0;
    const fetchMock = stubFetch((url) => {
      if (url === "/api/auth/refresh") return json({ signed_in: true });
      inboxCalls += 1;
      return inboxCalls === 1 ? json({ error: { code: "unauthorized" } }, 401) : json([]);
    });
    const api = await import("./api");
    await expect(api.getInbox()).resolves.toEqual([]);
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/inbox", "/api/auth/refresh", "/api/inbox"]);
  });

  it("signals sign-out when the refresh fails too", async () => {
    stubFetch(() => json({ error: { code: "unauthorized" } }, 401));
    const api = await import("./api");
    const signedOut = vi.fn();
    window.addEventListener(api.SIGNED_OUT_EVENT, signedOut);
    await expect(api.getInbox()).rejects.toMatchObject({ status: 401, unauthorized: true });
    expect(signedOut).toHaveBeenCalledTimes(1);
    window.removeEventListener(api.SIGNED_OUT_EVENT, signedOut);
  });
});

describe("AuthGate", () => {
  const health = (auth_enabled: boolean) => ({ status: "ok", demo_mode: "live", use_mocks: true, auth_enabled, mocked_routes: {} });

  it("renders the app unchanged when auth is off", async () => {
    const fetchMock = stubFetch(() => json(health(false)));
    const { AuthGate } = await import("./auth");
    render(<AuthGate><p>the app</p></AuthGate>);
    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => c[0] === "/api/auth/me")).toBe(false);
  });

  it("shows sign-in when auth is on and there is no session", async () => {
    stubFetch((url) => (url === "/api/health" ? json(health(true)) : json({ error: { code: "unauthorized" } }, 401)));
    const { AuthGate } = await import("./auth");
    render(<AuthGate><p>the app</p></AuthGate>);
    expect(await screen.findByText(/Use a password and code instead|Continue/)).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();
  });

  it("renders the app when signed in", async () => {
    stubFetch((url) =>
      url === "/api/health"
        ? json(health(true))
        : json({ user_id: "u", username: "demo", display_name: "Demo", role: "customer", passkeys: 0 }),
    );
    const { AuthGate } = await import("./auth");
    render(<AuthGate><p>the app</p></AuthGate>);
    expect(await screen.findByText("the app")).toBeInTheDocument();
  });
});
