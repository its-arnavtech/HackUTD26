import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowRight, ChevronRight, HeartHandshake, LoaderCircle } from "lucide-react";
import { confirmTransaction, postClicked } from "../api";
import { useInboxItem, useResult } from "../hooks";
import { isLinked } from "../linking";
import { ActionButton, ChecklistItem, EmptyState, Notice, PageTitle, WasThisYouCard } from "../components";
import { activitySummary, minutesAfter, recoveryChecklist, recoverySteps } from "../present";
import type { Action, ResultPoll, WasThisYouItem } from "../types";

export type RecoveryStage = "intro" | "checking" | "transfer" | "checklist";

const nouns: Record<WasThisYouItem["type"], string> = {
  transfer: "transfer",
  purchase: "purchase",
  bill: "bill payment",
  deposit: "deposit",
  withdrawal: "withdrawal",
};

/** "I clicked" → "Was this you?" per flagged item → checklist. Every step waits for a tap. */
export function RecoveryView({
  stage,
  linked = true,
  poll,
  item,
  remaining = 0,
  minutesAfterMessage,
  recognized = false,
  noActivity = false,
  checked = [],
  notice = "",
  busy = false,
  error = false,
  onClicked,
  onOnlyOpened,
  onAnswer,
  onToggle,
  onTrail,
  onDone,
  onRetry,
}: {
  stage: RecoveryStage;
  linked?: boolean;
  poll?: ResultPoll;
  item?: WasThisYouItem;
  /** Items still to confirm after this one. */
  remaining?: number;
  minutesAfterMessage?: number;
  recognized?: boolean;
  /** The activity check finished with nothing to confirm. */
  noActivity?: boolean;
  checked?: Action[];
  notice?: string;
  busy?: boolean;
  error?: boolean;
  onClicked?: () => void;
  onOnlyOpened?: () => void;
  onAnswer?: (wasMe: boolean) => void;
  onToggle?: (action: Action) => void;
  onTrail?: () => void;
  onDone?: () => void;
  onRetry?: () => void;
}) {
  if (error) {
    return (
      <div className="screen-pad recovery-screen">
        <EmptyState
          error
          title="We couldn’t check your activity."
          description="Nothing was changed. If you entered your details, call the number on the back of your card."
          onRetry={onRetry}
        />
      </div>
    );
  }

  if (stage === "intro") {
    return (
      <div className="screen-pad recovery-screen recovery-intro">
        <span className="recovery-art">
          <HeartHandshake size={45} />
        </span>
        <PageTitle
          eyebrow="You’re in the right place"
          description="These things happen. We’ll help you work through what comes next."
        >
          Let’s take it
          <br />
          step by step.
        </PageTitle>
        <div className="soft-panel">
          <h2>Did you enter information?</h2>
          <p>We can check for unfamiliar activity since the message arrived.</p>
        </div>
        {notice && <Notice>{notice}</Notice>}
        <ActionButton onClick={onClicked} disabled={busy} arrow>
          {linked ? "I clicked and entered my info" : "Link an account to check activity"}
        </ActionButton>
        <button className="text-button" onClick={onOnlyOpened}>
          I only opened the link
        </button>
        <p className="quiet-note">No changes are made to your account.</p>
      </div>
    );
  }

  if (stage === "checking") {
    return (
      <div className="screen-pad recovery-screen recovery-checking">
        <PageTitle eyebrow="Recent activity" description="We’re looking at what happened after the text arrived.">
          A moment
          <br />
          to double-check.
        </PageTitle>
        <div className="loading-screen" role="status">
          <LoaderCircle className="spin" size={22} />
          Checking activity since the text…
        </div>
        {poll && onTrail && (
          <button className="row-link" onClick={onTrail}>
            See how we’re checking
            <ChevronRight size={19} />
          </button>
        )}
      </div>
    );
  }

  if (stage === "transfer" && item) {
    const noun = nouns[item.type];
    return (
      <div className="screen-pad recovery-screen recovery-transfer">
        <PageTitle
          eyebrow="Recent activity"
          description={
            remaining > 0
              ? `A new ${noun} after the text. ${remaining} more to review after this.`
              : `A new ${noun} after the text.`
          }
        >
          A moment
          <br />
          to double-check.
        </PageTitle>
        {notice && <Notice>{notice}</Notice>}
        <WasThisYouCard
          item={item}
          minutesAfterMessage={minutesAfterMessage}
          onAnswer={(wasMe) => onAnswer?.(wasMe)}
          busy={busy}
        />
        <p className="quiet-note">Your answer guides the next step. We never move money.</p>
      </div>
    );
  }

  const result = poll?.status === "done" && poll.mode === "recovery" ? poll.result : undefined;
  const steps = recoveryChecklist(result);
  const done = steps.filter((step) => checked.includes(step)).length;
  const complete = done === steps.length;
  return (
    <div className="screen-pad recovery-screen recovery-checklist">
      <PageTitle
        eyebrow="Your recovery checklist"
        description={
          recognized
            ? "You recognized the activity. If you shared login details, these steps still matter."
            : "Start here. You can do one thing at a time."
        }
      >
        {complete ? "You’ve taken the next steps." : "You’re in control."}
      </PageTitle>
      {recognized ? (
        <Notice>Activity marked as recognized in this demo.</Notice>
      ) : (
        <div className="privacy-banner">
          <HeartHandshake size={23} />
          <p>
            {complete
              ? "Your checklist is complete."
              : noActivity && result
                ? activitySummary(result)
                : "If the transfer wasn’t yours, contact your bank promptly."}
          </p>
        </div>
      )}
      <div className="checklist">
        {steps.map((step) => {
          const copy = recoverySteps[step]!;
          return (
            <ChecklistItem
              key={step}
              label={copy.label}
              detail={copy.detail}
              checked={checked.includes(step)}
              onChange={() => onToggle?.(step)}
            />
          );
        })}
      </div>
      <p className="quiet-note left">
        {done} of {steps.length} marked complete by you. Checking a box records progress only.
      </p>
      <ActionButton onClick={onDone} icon={<ArrowRight size={20} />}>
        Return to messages
      </ActionButton>
      <p className="quiet-note">SentinelAI doesn’t freeze cards, change passwords, or place calls.</p>
    </div>
  );
}

export default function Recovery() {
  const { messageId = "msg_0001" } = useParams();
  const navigate = useNavigate();
  const message = useInboxItem(messageId);
  const [linked] = useState(isLinked);
  const [clicked, setClicked] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [checked, setChecked] = useState<Action[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const { poll, error, retry } = useResult(messageId, clicked);

  // Only the recovery run counts; a stale check-mode poll is still "checking".
  const recovery = poll?.mode === "recovery" ? poll : undefined;
  const finished = recovery?.status === "done";
  const items = finished ? recovery.was_this_you_items : [];
  const pending = items.filter((item) => answers[item.ref] === undefined);
  const current = pending[0];

  const stage: RecoveryStage = skipped
    ? "checklist"
    : !clicked
      ? "intro"
      : !finished
        ? "checking"
        : current
          ? "transfer"
          : "checklist";

  const startCheck = async () => {
    if (!linked) {
      navigate("/consent");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      await postClicked(messageId);
      setClicked(true);
    } catch {
      setNotice("That didn’t go through. Nothing was changed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const answer = async (wasMe: boolean) => {
    if (!current) return;
    setBusy(true);
    setNotice("");
    try {
      await confirmTransaction(current.ref, wasMe);
      setAnswers((all) => ({ ...all, [current.ref]: wasMe }));
    } catch {
      setNotice("That didn’t go through. Nothing was changed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const answered = Object.values(answers);
  return (
    <RecoveryView
      stage={stage}
      linked={linked}
      poll={recovery}
      item={current}
      remaining={Math.max(pending.length - 1, 0)}
      minutesAfterMessage={current ? minutesAfter(message?.received_at, current.at) : undefined}
      recognized={answered.length > 0 && answered.every(Boolean)}
      noActivity={finished && items.length === 0}
      checked={checked}
      notice={notice}
      busy={busy}
      error={clicked && error}
      onClicked={() => void startCheck()}
      onOnlyOpened={() => setSkipped(true)}
      onAnswer={(wasMe) => void answer(wasMe)}
      onToggle={(action) =>
        setChecked((all) => (all.includes(action) ? all.filter((a) => a !== action) : [...all, action]))
      }
      onTrail={() => navigate(`/trail/${encodeURIComponent(messageId)}`)}
      onDone={() => navigate("/inbox")}
      onRetry={retry}
    />
  );
}
