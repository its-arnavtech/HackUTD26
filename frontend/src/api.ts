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

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(res.status, `${init?.method ?? "GET"} ${path} failed with ${res.status}`);
  }
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
