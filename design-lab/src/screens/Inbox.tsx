import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowUpRight,
  LoaderCircle,
  MessageSquareText,
  ScanLine,
} from "lucide-react";
import { api } from "../api";
import { useData } from "../hooks";
import {
  ActionButton,
  EmptyState,
  PageTitle,
  VerdictBadge,
} from "../components";
export default function Inbox({
  state = "default",
  freezeChecking = false,
}: {
  state?: string;
  freezeChecking?: boolean;
}) {
  const navigate = useNavigate();
  const { data: messages } = useData(() => api.getInbox());
  const [checking, setChecking] = useState(state === "checking");
  const [checkDone, setCheckDone] = useState(false);
  useEffect(() => {
    setChecking(state === "checking");
    setCheckDone(false);
    if (state !== "checking" || freezeChecking) return;
    let active = true;
    api.runCheck().then(() => {
      if (active) {
        setChecking(false);
        setCheckDone(true);
      }
    });
    return () => {
      active = false;
    };
  }, [state, freezeChecking]);
  const run = () => {
    setChecking(true);
    setCheckDone(false);
    api.runCheck().then(() => {
      setChecking(false);
      setCheckDone(true);
    });
  };
  return (
    <div className="screen-pad inbox-screen">
      <PageTitle
        eyebrow="Your messages"
        description="A pause between a worrying text and what you do next."
      >
        One message.
        <br />A clearer mind.
      </PageTitle>
      {state === "empty" || state === "error" ? (
        <EmptyState
          error={state === "error"}
          onRetry={() => navigate("/inbox")}
        />
      ) : (
        <>
          <div className="inbox-caption">
            <span>Today</span>
            <span className="metadata">
              {messages?.length || 0} authored texts
            </span>
          </div>
          {messages?.map((message, i) => (
            <button
              key={message.id}
              className={`inbox-message ${i === 0 ? "featured-message" : ""}`}
              onClick={() =>
                (i !== 0 || !checking) &&
                navigate(i ? "/result?scenario=billing" : "/result")
              }
              disabled={checking && i === 0}
            >
              <div className="inbox-sender">
                <span className="message-avatar">
                  <MessageSquareText size={21} />
                </span>
                <strong>{message.brand}</strong>
                <span className="metadata">
                  {new Intl.DateTimeFormat("en-US", {
                    hour: "numeric",
                    minute: "2-digit",
                    timeZone: "America/Chicago",
                  }).format(new Date(message.received_at))}
                </span>
              </div>
              <p>{message.preview || message.text}</p>
              {i === 0 && checking ? (
                <span className="checking-chip" role="status">
                  <LoaderCircle className="spin" size={17} />
                  Checking…
                </span>
              ) : (
                <VerdictBadge verdict={message.verdict!} />
              )}
              <ArrowUpRight className="inbox-arrow" size={19} />
            </button>
          ))}
          {checking ? (
            <div className="checking-note" role="status">
              <span className="pulse-dot" />
              Checking the link, sender, and recent activity.
            </div>
          ) : (
            <ActionButton secondary onClick={run} icon={<ScanLine size={21} />}>
              {checkDone
                ? "Check complete · Run again"
                : "Check a new demo text"}
            </ActionButton>
          )}
          <div className="inbox-assurance">
            <span className="tiny-rule" />
            <p>You don’t have to decide alone.</p>
            <span className="metadata">
              Tap a message to see what we found.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
