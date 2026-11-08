import { useState } from "react";
import { AlertTriangle, Check, CircleHelp, MessageSquareText, ShieldAlert, ShieldCheck, Smartphone } from "lucide-react";
import { confirmTransaction, postAction } from "../api";
import { verdictLabel } from "../components";
import {
  actionLabels,
  actionReceipts,
  maskLinks,
  minutesAfter,
  nextStep,
  recoveryChecklist,
  recoverySteps,
} from "../present";
import type { Action, InboxItem, ResultPoll, Verdict } from "../types";

const verdictIcon: Record<Verdict, typeof ShieldAlert> = {
  likely_scam: ShieldAlert,
  unsure: CircleHelp,
  likely_safe: ShieldCheck,
};

/** What the customer sees for one message: the text, then the verdict, actions and recovery. */
export function CustomerPanel({
  message,
  poll,
  onClicked,
  busy = false,
}: {
  message?: InboxItem;
  poll?: ResultPoll;
  onClicked?: () => void;
  busy?: boolean;
}) {
  const [receipt, setReceipt] = useState<string>();
  const [answer, setAnswer] = useState<"yes" | "no">();
  const [answering, setAnswering] = useState(false);
  const [done, setDone] = useState<Set<Action>>(new Set());

  if (!message) {
    return (
      <div className="cx-empty">
        <MessageSquareText size={28} aria-hidden="true" />
        <p>Pick a scenario above, or text the SentinelAI number from your phone.</p>
      </div>
    );
  }

  const result = poll?.status === "done" ? poll.result : undefined;
  const recovery = poll?.mode === "recovery";
  const item = poll?.was_this_you_items[0];

  const act = async (action: Action) => {
    try {
      const r = await postAction(message.message_id, action);
      setReceipt(actionReceipts[action] ?? r.note);
    } catch {
      setReceipt("That didn’t go through. Nothing was sent.");
    }
  };

  const confirm = async (wasMe: boolean) => {
    if (!item) return;
    setAnswering(true);
    try {
      await confirmTransaction(item.ref, wasMe);
      setAnswer(wasMe ? "yes" : "no");
    } finally {
      setAnswering(false);
    }
  };

  return (
    <div className="cx-customer">
      <div className="cx-sms">
        <div className="cx-sms-head">
          {message.source === "sms" ? <Smartphone size={15} aria-hidden="true" /> : <MessageSquareText size={15} aria-hidden="true" />}
          <span>{message.source === "sms" ? "Texted to SentinelAI" : message.sender}</span>
        </div>
        <p>{maskLinks(message.text)}</p>
      </div>

      {!result && (
        <div className="cx-checking" role="status">
          <span className="cx-spinner" aria-hidden="true" />
          {recovery ? "Checking your recent account activity…" : "Checking this message…"}
          {poll && poll.trail.length > 0 && <span className="cx-muted"> {poll.trail.length} steps so far</span>}
        </div>
      )}

      {result && (
        <article className={`cx-verdict cx-verdict-${result.verdict}`}>
          <header>
            {(() => {
              const Icon = verdictIcon[result.verdict];
              return <Icon size={22} aria-hidden="true" />;
            })()}
            <h2>{verdictLabel(result.verdict, result.confidence_words)}</h2>
          </header>
          <p className="cx-reason">{result.reason}</p>
          {!recovery && <p className="cx-next">{nextStep(result, poll?.mode)}</p>}

          {!recovery && result.actions.length > 0 && (
            <div className="cx-actions">
              {result.actions.slice(0, 3).map((action) => (
                <button key={action} className="cx-button" onClick={() => void act(action)}>
                  {actionLabels[action]}
                </button>
              ))}
            </div>
          )}
          {receipt && (
            <p className="cx-receipt" role="status">
              <Check size={15} aria-hidden="true" /> {receipt}
            </p>
          )}
          {!recovery && result.verdict !== "likely_safe" && onClicked && (
            <button className="cx-link-button" onClick={onClicked} disabled={busy}>
              <AlertTriangle size={15} aria-hidden="true" /> I already tapped the link
            </button>
          )}
        </article>
      )}

      {recovery && result && item && !answer && (
        <article className="cx-card">
          <p className="cx-eyebrow">Activity after the text</p>
          <p className="cx-amount">${item.amount.toLocaleString("en-US", { minimumFractionDigits: 2 })}</p>
          <p>
            {item.type} at {item.payee}
            {minutesAfter(message.received_at, item.at) != null && ` · ${minutesAfter(message.received_at, item.at)} min after the text`}
          </p>
          <p className="cx-question">Was this you?</p>
          <div className="cx-actions">
            <button className="cx-button cx-button-primary" onClick={() => void confirm(false)} disabled={answering}>
              No, I don’t recognize it
            </button>
            <button className="cx-button" onClick={() => void confirm(true)} disabled={answering}>
              Yes, that was me
            </button>
          </div>
        </article>
      )}

      {recovery && result && (answer === "no" || !item) && (
        <article className="cx-card">
          <p className="cx-eyebrow">What to do now</p>
          <ol className="cx-checklist">
            {recoveryChecklist(result).map((action) => {
              const step = recoverySteps[action];
              if (!step) return null;
              const checked = done.has(action);
              return (
                <li key={action}>
                  <label>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setDone((current) => {
                          const next = new Set(current);
                          if (checked) next.delete(action);
                          else next.add(action);
                          return next;
                        })
                      }
                    />
                    <span>
                      <strong>{step.label}</strong>
                      <span className="cx-muted">{step.detail}</span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ol>
          <p className="cx-muted">We never move money for you.</p>
        </article>
      )}
      {recovery && answer === "yes" && (
        <p className="cx-receipt" role="status">
          <Check size={15} aria-hidden="true" /> Thanks. We didn’t flag anything else in the activity we checked.
        </p>
      )}
    </div>
  );
}
