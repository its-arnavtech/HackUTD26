import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useData } from "../hooks";
import {
  EmptyState,
  MessageBubble,
  Notice,
  PrivacyFootnote,
  ResultCard,
} from "../components";
import type { ResultState, ScenarioId } from "../types";
export default function Result({
  scenario = "bank",
  state = "scam",
}: {
  scenario?: ScenarioId;
  state?: ResultState;
}) {
  const { data } = useData(
    () => api.getScenario(scenario, state),
    [scenario, state],
  );
  const navigate = useNavigate();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  if (!data)
    return (
      <div className="loading-screen" role="status">
        Preparing your check…
      </div>
    );
  const primary = async () => {
    setBusy(true);
    const action =
      data.result.verdict === "likely_scam" && scenario !== "billing"
        ? "block_sender"
        : "open_official_app";
    const receipt = await api.performAction(data.message.id, action);
    setNotice(receipt.label);
    setBusy(false);
  };
  return (
    <div className="screen-pad result-screen">
      <MessageBubble
        message={data.message}
        small={scenario === "bank" && state === "scam"}
      />
      {notice && <Notice onClose={() => setNotice("")}>{notice}</Notice>}
      <ResultCard
        result={data.result}
        activity={data.activity_summary}
        nextStep={data.next_step}
        onPrimary={primary}
        onTrail={() => navigate(`/trail?scenario=${scenario}&state=${state}`)}
        busy={busy}
        officialAction={scenario === "billing"}
        primaryLabel={
          notice.startsWith("Sender blocked")
            ? "Sender blocked"
            : scenario === "billing"
              ? "Use the official app"
              : undefined
        }
      />
      <Link className="recovery-link" to="/recovery">
        I clicked this link
      </Link>
      <PrivacyFootnote />
    </div>
  );
}
export function ResultError() {
  const navigate = useNavigate();
  return (
    <div className="screen-pad">
      <EmptyState error onRetry={() => navigate("/inbox?state=checking")} />
    </div>
  );
}
