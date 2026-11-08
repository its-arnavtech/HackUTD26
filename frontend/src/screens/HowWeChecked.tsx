import { useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useResult } from "../hooks";
import { ActionButton, PageTitle, TrailStep } from "../components";
import type { TrailEntry } from "../types";
import { ResultError } from "./ResultCard";

/** The agent's plan, each tool call and the verdict, in order. New entries slide in as they arrive. */
export function TrailView({
  trail,
  checking = false,
  animate = true,
  onBack,
}: {
  trail: TrailEntry[];
  checking?: boolean;
  animate?: boolean;
  onBack?: () => void;
}) {
  // Entries already there on first paint stagger in; later arrivals animate at once.
  const firstBatch = useRef<number | null>(null);
  if (firstBatch.current === null && trail.length > 0) firstBatch.current = trail.length;
  return (
    <div className="screen-pad trail-screen">
      <PageTitle
        eyebrow="The reasoning, made visible"
        description="Each check has a purpose. Here’s what we found and why we looked."
      >
        How we
        <br />
        checked.
      </PageTitle>
      <div className="agent-label">
        <span className="status-dot" />
        Planned by Nemotron · Details hidden first
      </div>
      <div className="trail-list" aria-live="polite">
        {trail.map((entry, index) => (
          <TrailStep
            entry={entry}
            index={index < (firstBatch.current ?? 0) ? index : 0}
            key={entry.step}
            animate={animate}
          />
        ))}
      </div>
      {checking && (
        <div className="checking-note" role="status">
          <span className="pulse-dot" />
          Still checking. New steps appear here.
        </div>
      )}
      {onBack && (
        <ActionButton secondary onClick={onBack}>
          Back to your result
        </ActionButton>
      )}
    </div>
  );
}

export default function HowWeChecked() {
  const { messageId = "" } = useParams();
  const navigate = useNavigate();
  const { poll, failure, retry } = useResult(messageId);
  if (failure) return <ResultError failure={failure} onRetry={retry} />;
  return (
    <TrailView
      trail={poll?.trail ?? []}
      checking={!poll || poll.status !== "done"}
      onBack={() => navigate(`/result/${encodeURIComponent(messageId)}`)}
    />
  );
}
