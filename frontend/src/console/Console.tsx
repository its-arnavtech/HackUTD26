import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, MessageSquareText, Play, RotateCcw, Smartphone } from "lucide-react";
import { getInbox, postClicked, resetDemo } from "../api";
import { verdictLabel } from "../components";
import { useResult } from "../hooks";
import type { InboxItem } from "../types";
import { BehindTheScenes } from "./BehindTheScenes";
import { CustomerPanel } from "./CustomerPanel";
import { Shell } from "./Shell";

const SCENARIO_1 = "msg_0001";
const SCENARIO_3 = "msg_0003";
const INBOX_POLL_MS = 2000;

/** The inbox, refreshed every 2 s so a text sent to the SentinelAI number shows up on its own. */
function useLiveInbox() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [offline, setOffline] = useState(false);
  const load = useCallback(async () => {
    try {
      setItems(await getInbox());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), INBOX_POLL_MS);
    return () => clearInterval(timer);
  }, [load]);
  return { items, offline, reload: load };
}

/** One message: what the customer sees on the left, the backend on the right. */
export function MessageView({ message, onClickedDone }: { message?: InboxItem; onClickedDone?: () => void }) {
  const id = message?.message_id ?? "";
  const { poll, retry } = useResult(id, Boolean(message));
  const [busy, setBusy] = useState(false);

  const clicked = async () => {
    if (!message) return;
    setBusy(true);
    try {
      await postClicked(message.message_id);
      retry();
      onClickedDone?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cx-split">
      <section className="cx-panel" aria-label="What the customer sees">
        <p className="cx-eyebrow">What Linda sees</p>
        <CustomerPanel key={`${id}-${poll?.mode ?? "check"}`} message={message} poll={poll} onClicked={clicked} busy={busy} />
      </section>
      <BehindTheScenes message={message} poll={poll} />
    </div>
  );
}

export default function Console() {
  const { items, offline, reload } = useLiveInbox();
  const [selected, setSelected] = useState<string>();
  const [working, setWorking] = useState<string>();
  const [version, setVersion] = useState(0); // bumps to restart polling after reset or "she clicked"
  const seen = useRef<Set<string> | null>(null);

  // A new text that arrives by SMS opens on its own, so judges see it land.
  useEffect(() => {
    if (items.length === 0) return;
    if (seen.current === null) {
      seen.current = new Set(items.map((i) => i.message_id));
      return;
    }
    const fresh = items.find((i) => i.source === "sms" && !seen.current!.has(i.message_id));
    items.forEach((i) => seen.current!.add(i.message_id));
    if (fresh) {
      setSelected(fresh.message_id);
      setVersion((v) => v + 1);
    }
  }, [items]);

  const run = async (label: string, action: () => Promise<void>) => {
    setWorking(label);
    try {
      await action();
    } finally {
      setWorking(undefined);
    }
  };

  const scenario = (id: string) =>
    run(id, async () => {
      await resetDemo().catch(() => undefined); // with auth on, only an admin may reset; carry on without
      await reload();
      setSelected(id);
      setVersion((v) => v + 1);
    });

  const sheClicked = () =>
    run("clicked", async () => {
      const id = selected ?? SCENARIO_1;
      if (!selected) setSelected(id);
      await postClicked(id);
      setVersion((v) => v + 1);
    });

  const message = items.find((i) => i.message_id === selected);

  return (
    <Shell wide>
      <div className="cx-scenarios" role="toolbar" aria-label="Demo scenarios">
        <button className="cx-button cx-button-primary" onClick={() => void scenario(SCENARIO_1)} disabled={!!working}>
          <Play size={15} aria-hidden="true" /> Scenario 1: bank text
        </button>
        <button className="cx-button" onClick={() => void sheClicked()} disabled={!!working}>
          <AlertTriangle size={15} aria-hidden="true" /> She clicked
        </button>
        <button className="cx-button" onClick={() => void scenario(SCENARIO_3)} disabled={!!working}>
          <Play size={15} aria-hidden="true" /> Scenario 3: overdue bill
        </button>
        <button className="cx-button cx-button-ghost" onClick={() => void run("reset", async () => { await resetDemo(); setSelected(undefined); await reload(); })} disabled={!!working}>
          <RotateCcw size={15} aria-hidden="true" /> Reset
        </button>
        <span className="cx-hint">
          <Smartphone size={15} aria-hidden="true" /> Or text the SentinelAI number: it appears here live.
        </span>
      </div>

      {offline && <p className="cx-alert">Can’t reach the SentinelAI API. Is the backend running?</p>}

      <div className="cx-layout">
        <aside className="cx-inbox" aria-label="Messages">
          <p className="cx-eyebrow">Messages</p>
          <ul>
            {items.map((item) => (
              <li key={item.message_id}>
                <button
                  className={`cx-inbox-row ${item.message_id === selected ? "active" : ""}`}
                  onClick={() => {
                    setSelected(item.message_id);
                    setVersion((v) => v + 1);
                  }}
                >
                  <span className="cx-inbox-top">
                    {item.source === "sms" ? <Smartphone size={13} aria-hidden="true" /> : <MessageSquareText size={13} aria-hidden="true" />}
                    <strong>{item.source === "sms" ? "Texted in" : item.sender}</strong>
                  </span>
                  <span className="cx-inbox-text">{item.text}</span>
                  {item.verdict && (
                    <span className={`cx-pill cx-pill-${item.verdict}`}>{verdictLabel(item.verdict, item.confidence_words)}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <MessageView key={`${selected ?? "none"}-${version}`} message={message} />
      </div>
    </Shell>
  );
}

/** `/r/:messageId`: the page an SMS reply links to, phone-friendly. */
export function ResultPage() {
  const { messageId = "" } = useParams();
  const { items } = useLiveInbox();
  const message = items.find((i) => i.message_id === messageId);
  return (
    <Shell>
      <MessageView key={messageId} message={message} />
    </Shell>
  );
}
