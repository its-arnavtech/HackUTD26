import { useCallback, useEffect, useRef, useState } from "react";
import type { DependencyList } from "react";
import { ApiError, failureOf, getHealth, getInbox, pollResult, postMessage, type Failure, type Health } from "./api";
import type { InboxItem, ResultPoll } from "./types";

/** Load once per `deps`. `retry` loads again; `failure` says why it failed (offline, not found, not wired yet). */
export function useData<T>(loader: () => Promise<T>, deps: DependencyList = []) {
  const [data, setData] = useState<T>();
  const [failure, setFailure] = useState<Failure>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setData(undefined);
    setFailure(undefined);
    loader()
      .then((value) => {
        if (active) setData(value);
      })
      .catch((err: unknown) => {
        if (active) setFailure(failureOf(err));
      });
    return () => {
      active = false;
    };
  }, [...deps, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error: failure !== undefined, failure, loading: data === undefined && failure === undefined, retry };
}

let health: Promise<Health | undefined> | undefined;

/** `/api/health`, fetched once per page load. Undefined while loading, or if it failed (then it's asked again next time). */
export function useHealth() {
  return useHealthState().health;
}

/** Like `useHealth`, plus `settled`: true once health answered or failed (L13's auth gate waits for it). */
export function useHealthState() {
  const [state, setState] = useState<{ health?: Health; settled: boolean }>({ settled: false });
  useEffect(() => {
    let active = true;
    health ??= getHealth().catch(() => {
      health = undefined;
      return undefined;
    });
    void health.then((h) => {
      if (active) setState({ health: h, settled: true });
    });
    return () => {
      active = false;
    };
  }, []);
  return state;
}

/** Tests only: forget the cached health answer. */
export const forgetHealth = () => {
  health = undefined;
};

/** Synthetic scenario 1 text (POC_MVP 4.3) for the "check a new demo text" button. */
export const DEMO_MESSAGE = {
  sender: "+15550104477",
  text: "Capital One Alert: unusual sign-in for Linda. Your account will be locked in 2 hours. Verify now: https://capone-verify-alert.com/verify",
};

/** Overlay the latest poll on an inbox row, so a finished check shows its verdict. */
export function withProgress(item: InboxItem, poll?: ResultPoll): InboxItem {
  if (!poll) return item;
  return {
    ...item,
    status: poll.status,
    verdict: poll.result?.verdict ?? item.verdict,
    confidence_words: poll.result?.confidence_words ?? item.confidence_words,
  };
}

export const newestFirst = (rows: InboxItem[]) =>
  [...rows].sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at));

/** Errors in a row before a check is shown as unavailable. A 404 fails at once. */
const MAX_POLL_ERRORS = 3;

/** A check still running after this long stops polling and offers a retry instead of spinning forever. */
export const MAX_CHECK_MS = 180_000;

export type ResultFailure = Failure | "slow";

/** Inbox rows, newest first, with every unfinished check polled until it is done. */
export function useInbox() {
  const [items, setItems] = useState<InboxItem[]>();
  const [failure, setFailure] = useState<Failure>();
  const [notice, setNotice] = useState("");
  const [posting, setPosting] = useState(false);
  const [progress, setProgress] = useState<Record<string, ResultPoll>>({});
  const pollers = useRef(new Map<string, () => void>());

  const watch = useCallback((rows: InboxItem[]) => {
    for (const row of rows) {
      if (row.status === "done" || pollers.current.has(row.message_id)) continue;
      let failures = 0;
      const stop = pollResult(
        row.message_id,
        (poll) => {
          failures = 0;
          setProgress((current) => ({ ...current, [row.message_id]: poll }));
        },
        // A row whose check can't be read stops polling; reloading the inbox (retry) starts it again.
        (err) => {
          failures += 1;
          if ((err instanceof ApiError && err.notFound) || failures >= MAX_POLL_ERRORS) {
            stop();
            pollers.current.delete(row.message_id);
          }
        },
      );
      pollers.current.set(row.message_id, stop);
    }
  }, []);

  const load = useCallback(async () => {
    setFailure(undefined);
    try {
      const rows = await getInbox();
      setItems(rows);
      watch(rows);
    } catch (err) {
      setFailure(failureOf(err));
    }
  }, [watch]);

  useEffect(() => {
    const active = pollers.current;
    void load();
    return () => {
      active.forEach((stop) => stop());
      active.clear();
    };
  }, [load]);

  const checkNew = useCallback(async () => {
    setPosting(true);
    setNotice("");
    try {
      await postMessage({ ...DEMO_MESSAGE, received_at: new Date().toISOString() });
      await load();
    } catch {
      setNotice("That didn’t go through. No message was added. Please try again.");
    } finally {
      setPosting(false);
    }
  }, [load]);

  const dismissNotice = useCallback(() => setNotice(""), []);
  const rows = items && newestFirst(items.map((item) => withProgress(item, progress[item.message_id])));

  return {
    items: rows,
    progress,
    error: failure !== undefined,
    failure,
    notice,
    dismissNotice,
    posting,
    retry: load,
    checkNew,
  };
}

/**
 * Poll one message's result until it is done. `retry` starts polling again after an error.
 * With `enabled` false nothing is polled (recovery waits for the customer's tap).
 * A check still unfinished after `maxMs` stops with the failure "slow".
 */
export function useResult(messageId: string, enabled = true, maxMs = MAX_CHECK_MS) {
  const [poll, setPoll] = useState<ResultPoll>();
  const [failure, setFailure] = useState<ResultFailure>();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setPoll(undefined);
    setFailure(undefined);
    if (!enabled) return;
    let failures = 0;
    const started = Date.now();
    const stop = pollResult(
      messageId,
      (next) => {
        failures = 0;
        setPoll(next);
        if (next.status !== "done" && Date.now() - started > maxMs) {
          stop();
          setFailure("slow");
        }
      },
      (err) => {
        failures += 1;
        if ((err instanceof ApiError && err.notFound) || failures >= MAX_POLL_ERRORS) {
          stop();
          setFailure(failureOf(err));
        }
      },
    );
    return stop;
  }, [messageId, attempt, enabled, maxMs]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { poll, error: failure !== undefined, failure, retry };
}

/** The inbox row for one message, for the text shown above its result. */
export function useInboxItem(messageId: string) {
  const { data } = useData(() => getInbox(), [messageId]);
  return data?.find((item) => item.message_id === messageId);
}
