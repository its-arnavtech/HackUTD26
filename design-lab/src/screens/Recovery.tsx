import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, HeartHandshake } from "lucide-react";
import { api } from "../api";
import { useData } from "../hooks";
import {
  ActionButton,
  ChecklistItem,
  Notice,
  PageTitle,
  WasThisYouCard,
} from "../components";
export default function Recovery({ state = "intro" }: { state?: string }) {
  const navigate = useNavigate();
  const { data } = useData(() => api.getRecovery());
  const [stage, setStage] = useState(state);
  const [busy, setBusy] = useState(false);
  const [recognized, setRecognized] = useState(false);
  const [checked, setChecked] = useState<string[]>(
    state === "complete" ? ["freeze", "password", "call"] : [],
  );
  const answer = async (wasMe: boolean) => {
    if (!data) return;
    setBusy(true);
    await api.confirmTransaction(data.transaction.ref, wasMe);
    setRecognized(wasMe);
    setStage("checklist");
    setBusy(false);
  };
  return (
    <div className={`screen-pad recovery-screen recovery-${stage}`}>
      {stage === "intro" ? (
        <>
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
            <p>
              We can check for unfamiliar activity since the message arrived.
            </p>
          </div>
          <ActionButton
            onClick={() =>
              data?.linked ? setStage("transfer") : navigate("/consent")
            }
            arrow
          >
            {data?.linked === false
              ? "Link an account to check activity"
              : "I clicked and entered my info"}
          </ActionButton>
          <button
            className="text-button"
            onClick={() => {
              setRecognized(false);
              setStage("checklist");
            }}
          >
            I only opened the link
          </button>
          <p className="quiet-note">No changes are made to your account.</p>
        </>
      ) : stage === "transfer" ? (
        <>
          <PageTitle
            eyebrow="Recent activity"
            description="A new transfer after the text."
          >
            A moment
            <br />
            to double-check.
          </PageTitle>
          {data && (
            <WasThisYouCard
              transaction={data.transaction}
              onAnswer={answer}
              busy={busy}
            />
          )}
          <p className="quiet-note">
            Your answer guides the next step. We never move money.
          </p>
        </>
      ) : (
        <>
          <PageTitle
            eyebrow="Your recovery checklist"
            description={
              recognized
                ? "You recognized the transfer. If you shared login details, these steps still matter."
                : "Start here. You can do one thing at a time."
            }
          >
            {checked.length === 3
              ? "You’ve taken the next steps."
              : "You’re in control."}
          </PageTitle>
          {recognized ? (
            <Notice>Transfer marked as recognized in this demo.</Notice>
          ) : (
            <div className="privacy-banner">
              <HeartHandshake size={23} />
              <p>
                {state === "complete"
                  ? "Your checklist is complete."
                  : "If the transfer wasn’t yours, contact your bank promptly."}
              </p>
            </div>
          )}
          <div className="checklist">
            {data?.items.map((item) => (
              <ChecklistItem
                key={item.id}
                label={item.label}
                detail={item.detail}
                checked={checked.includes(item.id)}
                onChange={() =>
                  setChecked((current) =>
                    current.includes(item.id)
                      ? current.filter((x) => x !== item.id)
                      : [...current, item.id],
                  )
                }
              />
            ))}
          </div>
          <p className="quiet-note left">
            {checked.length} of 3 marked complete by you. Checking a box records
            progress only.
          </p>
          <ActionButton
            onClick={() => navigate("/inbox")}
            icon={<ArrowRight size={20} />}
          >
            Return to messages
          </ActionButton>
          <p className="quiet-note">
            SentinelAI doesn’t freeze cards, change passwords, or place calls.
          </p>
        </>
      )}
    </div>
  );
}
