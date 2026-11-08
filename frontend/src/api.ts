// One typed function per route in POC_MVP.md section 7.1.
import type {
  Action,
  ActionResponse,
  Campaign,
  ClickedResponse,
  ConfirmResponse,
  DemoResetResponse,
  InboxItem,
  MessageIn,
  Metrics,
  PostMessageResponse,
  PrivacyView,
  ResultPoll,
} from "./types";

/**
 * Every failed call. The backend sends one error shape (`backend/app/errors.py`):
 * `{detail, error: {code, message, details}}`. `status` 0 means the API couldn't be reached.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code = "",
    /** The issue that wires this route, when the backend answers 501 (for example "L6"). */
    public issue = "",
  ) {
    super(message);
  }

  /** The route exists in POC_MVP 7.1 but its live version hasn't landed, and its mock is off. */
  get notWiredYet() {
    return this.status === 501;
  }

  get notFound() {
    return this.status === 404;
  }

  get offline() {
    return this.status === 0;
  }
}

/** How a failed call reads on screen. Never shows the backend's own message. */
export type Failure = "offline" | "not_found" | "not_wired" | "error";

export function failureOf(err: unknown): Failure {
  if (!(err instanceof ApiError)) return "error";
  if (err.offline) return "offline";
  if (err.notFound) return "not_found";
  if (err.notWiredYet) return "not_wired";
  return "error";
}

/** A call that hasn't answered by now is treated as unreachable, so the screen can offer a retry. */
const TIMEOUT_MS = 15000;

async function errorFrom(res: Response, label: string): Promise<ApiError> {
  let code = "";
  let issue = "";
  try {
    const body = (await res.json()) as { error?: { code?: string; details?: { issue?: unknown } } };
    code = body.error?.code ?? "";
    issue = typeof body.error?.details?.issue === "string" ? body.error.details.issue : "";
  } catch {
    // Not JSON (a proxy error page, say): the status is enough.
  }
  return new ApiError(res.status, `${label} failed with ${res.status}`, code, issue);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const label = `${init?.method ?? "GET"} ${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...init,
      signal: controller.signal,
    });
  } catch {
    throw new ApiError(0, `${label} could not reach the API`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw await errorFrom(res, label);
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const getInbox = () => request<InboxItem[]>("/api/inbox");

export const postMessage = (body: MessageIn) => post<PostMessageResponse>("/api/messages", body);

export const getResult = (messageId: string) =>
  request<ResultPoll>(`/api/messages/${encodeURIComponent(messageId)}/result`);

export const postClicked = (messageId: string) =>
  post<ClickedResponse>(`/api/messages/${encodeURIComponent(messageId)}/clicked`);

export const confirmTransaction = (ref: string, wasMe: boolean) =>
  post<ConfirmResponse>(`/api/transactions/${encodeURIComponent(ref)}/confirm`, { was_me: wasMe });

/** Only call after the customer taps. */
export const postAction = (messageId: string, action: Action) =>
  post<ActionResponse>("/api/actions", { message_id: messageId, action });

export const getPrivacy = (messageId: string) =>
  request<PrivacyView>(`/api/privacy/${encodeURIComponent(messageId)}`);

export const getCampaigns = () => request<Campaign[]>("/api/campaigns");

export const getMetrics = () => request<Metrics>("/api/metrics");

export const resetDemo = () => post<DemoResetResponse>("/api/demo/reset");

/**
 * `GET /api/health`: which routes serve their mock (`USE_MOCKS`, `MOCK_ROUTES`, `LIVE_ROUTES`).
 * Not a DATA_SPEC contract, so the type lives here rather than in `types.ts`. Never carries a key.
 */
export interface Health {
  status: string;
  demo_mode: string;
  use_mocks: boolean;
  mocked_routes: Record<string, boolean>;
}

export const getHealth = () => request<Health>("/api/health");

/**
 * Poll the result every second until `done`, calling `onUpdate` with each response.
 * Returns a function that stops polling.
 */
export function pollResult(
  messageId: string,
  onUpdate: (poll: ResultPoll) => void,
  onError?: (err: unknown) => void,
  intervalMs = 1000,
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const tick = async () => {
    if (stopped) return;
    try {
      const poll = await getResult(messageId);
      if (stopped) return;
      onUpdate(poll);
      if (poll.status === "done") return;
    } catch (err) {
      onError?.(err);
    }
    if (!stopped) timer = setTimeout(tick, intervalMs);
  };

  void tick();
  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
