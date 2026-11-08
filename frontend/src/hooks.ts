import { useCallback, useEffect, useRef, useState } from "react";
import type { DependencyList } from "react";
import { getInbox, pollResult, postMessage } from "./api";
import type { InboxItem, ResultPoll } from "./types";

export function useData<T>(loader: () => Promise<T>, deps: DependencyList = []) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setData(undefined);
    setError(false);
    loader()
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, deps);
  return { data, error };
}

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

/** Inbox rows, newest first, with every unfinished check polled until it is done. */
export function useInbox() {
  const [items, setItems] = useState<InboxItem[]>();
  const [error, setError] = useState(false);
  const [posting, setPosting] = useState(false);
  const [progress, setProgress] = useState<Record<string, ResultPoll>>({});
  const pollers = useRef(new Map<string, () => void>());

  const watch = useCallback((rows: InboxItem[]) => {
    for (const row of rows) {
      if (row.status === "done" || pollers.current.has(row.message_id)) continue;
      const stop = pollResult(row.message_id, (poll) =>
        setProgress((current) => ({ ...current, [row.message_id]: poll })),
      );
      pollers.current.set(row.message_id, stop);
    }
  }, []);

  const load = useCallback(async () => {
    setError(false);
    try {
      const rows = await getInbox();
      setItems(rows);
      watch(rows);
    } catch {
      setError(true);
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
    try {
      await postMessage({ ...DEMO_MESSAGE, received_at: new Date().toISOString() });
      await load();
    } catch {
      setError(true);
    } finally {
      setPosting(false);
    }
  }, [load]);

  const rows = items && newestFirst(items.map((item) => withProgress(item, progress[item.message_id])));

  return { items: rows, progress, error, posting, retry: load, checkNew };
}
