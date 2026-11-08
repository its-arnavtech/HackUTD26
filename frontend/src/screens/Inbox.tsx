import { useNavigate } from "react-router-dom";
import { ArrowUpRight, LoaderCircle, MessageSquareText, ScanLine } from "lucide-react";
import { useInbox } from "../hooks";
import { ActionButton, EmptyState, LoadFailure, Notice, PageTitle, VerdictBadge, excerpt } from "../components";
import type { Failure } from "../api";
import type { InboxItem, ResultPoll } from "../types";

const time = (value: string) =>
  new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
  }).format(new Date(value));

/** The sender exactly as the text arrived, formatted like a phone inbox would. */
export function senderLabel(sender: string) {
  const us = sender.match(/^\+?1?(\d{3})(\d{3})(\d{4})$/);
  return us ? `(${us[1]}) ${us[2]}-${us[3]}` : sender;
}

const isChecking = (item: InboxItem) => item.status !== "done";

/** What the check is doing right now, from the newest trail entry. */
function checkingNote(poll?: ResultPoll) {
  const latest = poll?.trail.at(-1);
  if (!latest) return "Checking this message.";
  if (latest.kind === "plan") return latest.finding || "Making a plan.";
  return latest.why ? `${latest.why}.`.replace(/\.\.$/, ".") : "Checking this message.";
}

export function InboxView({
  items,
  progress = {},
  state = "ready",
  failure,
  notice = "",
  posting = false,
  onOpen,
  onCheckNew,
  onRetry,
  onDismissNotice,
}: {
  items: InboxItem[];
  progress?: Record<string, ResultPoll>;
  state?: "ready" | "loading" | "empty" | "error";
  failure?: Failure;
  notice?: string;
  posting?: boolean;
  onOpen?: (messageId: string) => void;
  onCheckNew?: () => void;
  onRetry?: () => void;
  onDismissNotice?: () => void;
}) {
  const checkingItem = items.find(isChecking);
  const empty = state === "empty" || (state === "ready" && items.length === 0);
  return (
    <div className="screen-pad inbox-screen">
      <PageTitle eyebrow="Your messages" description="A closer look at the texts that need your attention.">
        Your messages
      </PageTitle>
      {notice && <Notice onClose={onDismissNotice}>{notice}</Notice>}
      {state === "error" ? (
        <LoadFailure
          failure={failure === "not_found" ? undefined : failure}
          title="We couldn’t load your messages."
          description="Nothing was checked yet. Don’t use any links while you wait."
          onRetry={onRetry}
          retryLabel="Load messages again"
        />
      ) : empty ? (
        <EmptyState onRetry={onCheckNew} />
      ) : (
        <>
          <div className="inbox-caption">
            <span>Today</span>
            <span className="metadata">
              {state === "loading" ? "Loading…" : `${items.length} ${items.length === 1 ? "text" : "texts"}`}
            </span>
          </div>
          {items.map((item, i) => (
            <button
              key={item.message_id}
              className={`inbox-message ${i === 0 ? "featured-message" : ""}`}
              onClick={() => onOpen?.(item.message_id)}
              disabled={isChecking(item)}
            >
              <div className="inbox-sender">
                <span className="message-avatar">
                  <MessageSquareText size={21} />
                </span>
                <strong>{senderLabel(item.sender)}</strong>
                <span className="metadata">{time(item.received_at)}</span>
              </div>
              <p>{excerpt(item.text)}</p>
              {isChecking(item) ? (
                <span className="checking-chip" role="status">
                  <LoaderCircle className="spin" size={17} />
                  Checking…
                </span>
              ) : (
                item.verdict && <VerdictBadge verdict={item.verdict} confidence={item.confidence_words} />
              )}
              <ArrowUpRight className="inbox-arrow" size={19} />
            </button>
          ))}
          {checkingItem ? (
            <div className="checking-note" role="status">
              <span className="pulse-dot" />
              {checkingNote(progress[checkingItem.message_id])}
            </div>
          ) : (
            onCheckNew &&
            state === "ready" && (
              <ActionButton secondary onClick={onCheckNew} disabled={posting} icon={<ScanLine size={21} />}>
                {posting ? "One moment…" : "Check a new demo text"}
              </ActionButton>
            )
          )}
          <div className="inbox-assurance">
            <span className="tiny-rule" />
            <p>You don’t have to decide alone.</p>
            <span className="metadata">Tap a message to see what we found.</span>
          </div>
        </>
      )}
    </div>
  );
}

export default function Inbox() {
  const navigate = useNavigate();
  const { items, progress, error, failure, notice, dismissNotice, posting, retry, checkNew } = useInbox();
  return (
    <InboxView
      items={items ?? []}
      progress={progress}
      state={error ? "error" : items ? "ready" : "loading"}
      failure={failure}
      notice={notice}
      onDismissNotice={dismissNotice}
      posting={posting}
      onOpen={(id) => navigate(`/result/${encodeURIComponent(id)}`)}
      onCheckNew={() => void checkNew()}
      onRetry={() => void retry()}
    />
  );
}
