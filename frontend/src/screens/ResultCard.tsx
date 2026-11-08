import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronRight, LoaderCircle } from "lucide-react";
import { failureOf, getPrivacy, postAction } from "../api";
import { useData, useInboxItem, useResult } from "../hooks";
import {
  LoadFailure,
  MessageBubble,
  Notice,
  PrivacyFootnote,
  ResultCard as ResultCardView,
  type LoadFailureKind,
} from "../components";
import {
  actionDone,
  actionLabels,
  actionReceipts,
  activitySummary,
  claimedBrand as brandFromPrivacy,
  maskLinks,
  nextStep,
  primaryAction,
  redactedText,
  redactionMatches,
} from "../present";
import type { Action, ResultPoll } from "../types";

/** The check couldn't be read: offline, unknown message, too slow, or another error. Retry polls again. */
export function ResultError({ failure, onRetry }: { failure?: LoadFailureKind; onRetry?: () => void }) {
  return (
    <div className="screen-pad">
      <LoadFailure failure={failure} onRetry={onRetry} retryLabel="Try the check again" />
    </div>
  );
}

/** Verdict, confidence and reason in words, one primary action, and the way into the trail. */
export function ResultView({
  poll,
  messageText,
  claimedBrand,
  notice = "",
  done,
  busy = false,
  error = false,
  failure,
  onAction,
  onDismissNotice,
  onTrail,
  onRetry,
}: {
  poll?: ResultPoll;
  messageText?: string;
  claimedBrand?: string | null;
  notice?: string;
  done?: Action;
  busy?: boolean;
  error?: boolean;
  failure?: LoadFailureKind;
  onAction?: (action: Action) => void;
  onDismissNotice?: () => void;
  onTrail?: () => void;
  onRetry?: () => void;
}) {
  if (error || failure) return <ResultError failure={failure} onRetry={onRetry} />;
  const result = poll?.status === "done" ? poll.result : undefined;
  if (!poll || !result) {
    return (
      <div className="screen-pad result-screen">
        {messageText && <MessageBubble text={messageText} claimedBrand={claimedBrand} small />}
        <div className="loading-screen" role="status">
          <LoaderCircle className="spin" size={22} />
          Checking this message…
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
  const action = primaryAction(result);
  const primaryLabel = action && (done === action ? actionDone[action] : undefined);
  return (
    <div className="screen-pad result-screen">
      {messageText && <MessageBubble text={messageText} claimedBrand={claimedBrand} small />}
      {notice && <Notice onClose={onDismissNotice}>{notice}</Notice>}
      <ResultCardView
        result={result}
        activity={activitySummary(result)}
        nextStep={nextStep(result, poll.mode)}
        onPrimary={() => action && onAction?.(action)}
        onTrail={() => onTrail?.()}
        busy={busy}
        officialAction={action !== "block_sender"}
        primaryLabel={primaryLabel || (action ? actionLabels[action] : "Use the official app")}
      />
      {poll.mode === "check" && (
        <Link className="recovery-link" to={`/recovery/${encodeURIComponent(poll.message_id)}`}>
          I clicked this link
        </Link>
      )}
      <PrivacyFootnote messageId={poll.message_id} />
    </div>
  );
}

export default function ResultCard() {
  const { messageId = "" } = useParams();
  const navigate = useNavigate();
  const { poll, failure, retry } = useResult(messageId);
  const item = useInboxItem(messageId);
  const { data: privacy } = useData(() => getPrivacy(messageId), [messageId]);
  const redacted = privacy ? redactedText(privacy) : undefined;
  const useRedacted = Boolean(item && redacted && redactionMatches(item.text, redacted));
  const [notice, setNotice] = useState("");
  const [done, setDone] = useState<Action>();
  const [busy, setBusy] = useState(false);

  const act = async (action: Action) => {
    setBusy(true);
    try {
      await postAction(messageId, action);
      setNotice(actionReceipts[action]);
      setDone(action);
    } catch (err) {
      setNotice(
        failureOf(err) === "not_wired"
          ? "This action isn’t connected yet in this demo. Nothing was changed."
          : "That didn’t go through. Nothing was changed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <ResultView
      poll={poll}
      messageText={item ? (useRedacted ? redacted : maskLinks(item.text)) : undefined}
      claimedBrand={useRedacted && privacy ? brandFromPrivacy(privacy) : undefined}
      notice={notice}
      done={done}
      busy={busy}
      failure={failure}
      onAction={(action) => void act(action)}
      onDismissNotice={() => setNotice("")}
      onTrail={() => navigate(`/trail/${encodeURIComponent(messageId)}`)}
      onRetry={retry}
    />
  );
}
