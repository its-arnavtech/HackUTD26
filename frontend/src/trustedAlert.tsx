// L16: "Alert my trusted contact" in the recovery checklist (phone demo and console).
// The customer taps; the backend calls their trusted contact and emails them if the call
// isn't answered. We poll the alert every 2 s while it is "calling", for at most 120 s.
import { useCallback, useEffect, useRef, useState } from "react";
import { Phone } from "lucide-react";
import { getAlertStatus, postAlertAction, type AlertStatus } from "./api";
import { ActionButton, Notice } from "./components";
import { maskLinks } from "./present";

export const ALERT_POLL_MS = 2000;
export const ALERT_MAX_MS = 120_000;

export const ALERT_BUTTON = "Alert my trusted contact";

/** What the customer reads for an alert. `showText` adds "Here's what to tell them:" + alert_text. */
export function alertMessage(status: AlertStatus, timedOut = false): { line: string; showText: boolean } {
  const tag = status.simulated ? " (simulated)" : "";
  if (status.state === "calling" && !timedOut) return { line: `Calling your trusted contact…${tag}`, showText: false };
  const outcome = status.state === "calling" ? null : status.call_outcome;
  if (outcome === "answered") return { line: `They picked up.${tag}`, showText: false };
  if (status.email_sent) {
    if (outcome === "voicemail") return { line: `They didn’t pick up. We left a voicemail and emailed them.${tag}`, showText: false };
    if (outcome === "no_answer") return { line: `They didn’t pick up. We emailed them.${tag}`, showText: false };
    return { line: `We couldn’t call them, so we emailed them.${tag}`, showText: false };
  }
  return { line: `We couldn’t reach them. Here’s what to tell them:${tag}`, showText: true };
}

/** Starts the alert on tap, then polls while the call is ringing. */
export function useTrustedAlert(messageId?: string, pollMs = ALERT_POLL_MS, maxMs = ALERT_MAX_MS) {
  const [status, setStatus] = useState<AlertStatus>();
  const [note, setNote] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [tick, setTick] = useState(0);
  const startedAt = useRef(0);

  const start = useCallback(async () => {
    if (!messageId) return;
    setBusy(true);
    setProblem(undefined);
    setNote(undefined);
    setTimedOut(false);
    try {
      const r = await postAlertAction(messageId);
      startedAt.current = Date.now();
      setStatus(r.alert);
      if (!r.alert) setNote(r.note);
    } catch {
      setProblem("That didn’t go through. Nothing was sent.");
    } finally {
      setBusy(false);
    }
  }, [messageId]);

  const calling = status?.state === "calling" && !timedOut;

  useEffect(() => {
    if (!calling || !messageId) return;
    let live = true;
    const timer = setTimeout(async () => {
      if (Date.now() - startedAt.current >= maxMs) {
        setTimedOut(true);
        return;
      }
      try {
        const next = await getAlertStatus(messageId);
        if (live) setStatus(next);
      } catch {
        // A missed poll: try again on the next tick until the 120 s limit.
      }
      if (live) setTick((n) => n + 1);
    }, pollMs);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [calling, messageId, pollMs, maxMs, tick]);

  return { status, note, problem, busy, calling, timedOut, start };
}

/** The status line plus, when nobody was reached, the content-free alert as plain text. */
export function AlertStatusText({ status, timedOut }: { status: AlertStatus; timedOut: boolean }) {
  const { line, showText } = alertMessage(status, timedOut);
  return (
    <span className="alert-status">
      {line}
      {showText && status.alert_text && (
        <>
          {" "}
          <q className="alert-text">{maskLinks(status.alert_text)}</q>
        </>
      )}
    </span>
  );
}

/** Phone demo: a secondary button under the checklist, status in the calm Notice style. */
export function TrustedAlertPhone({ messageId }: { messageId: string }) {
  const { status, note, problem, busy, calling, timedOut, start } = useTrustedAlert(messageId);
  return (
    <div className="trusted-alert">
      <ActionButton secondary onClick={() => void start()} disabled={busy || calling} icon={<Phone size={19} />}>
        {ALERT_BUTTON}
      </ActionButton>
      {status && (
        <Notice>
          <AlertStatusText status={status} timedOut={timedOut} />
        </Notice>
      )}
      {!status && note && <Notice>{note}</Notice>}
      {problem && <Notice>{problem}</Notice>}
    </div>
  );
}

/** Console: same behaviour in the console's .cx look. */
export function TrustedAlertConsole({ messageId, label = ALERT_BUTTON }: { messageId: string; label?: string }) {
  const { status, note, problem, busy, calling, timedOut, start } = useTrustedAlert(messageId);
  return (
    <div className="cx-trusted-alert">
      <button className="cx-button cx-button-primary" onClick={() => void start()} disabled={busy || calling}>
        <Phone size={15} aria-hidden="true" /> {label}
      </button>
      {(status || note || problem) && (
        <p className={problem ? "cx-alert" : "cx-receipt"} role="status">
          {status ? <AlertStatusText status={status} timedOut={timedOut} /> : (problem ?? note)}
        </p>
      )}
    </div>
  );
}
