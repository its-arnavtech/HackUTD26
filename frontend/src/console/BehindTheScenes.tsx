import { useEffect, useState } from "react";
import {
  Brain,
  CircleDot,
  Gavel,
  Inbox,
  Landmark,
  Link2,
  ListChecks,
  Loader2,
  Megaphone,
  Repeat,
  ScanSearch,
  ShieldOff,
  Sigma,
  UserCheck,
  Users,
} from "lucide-react";
import { getPrivacy } from "../api";
import { fieldLabel, isRedactionTag, recipientLabel, splitRedacted } from "../present";
import type { InboxItem, PrivacyView, ResultPoll, ToolName } from "../types";
import { buildRows, elapsedSeconds, type Row } from "./timeline";

const toolIcons: Record<ToolName, typeof Link2> = {
  check_link: Link2,
  check_sender: UserCheck,
  match_campaign: Users,
  nessie_recent_activity: Landmark,
  nessie_bill_status: Landmark,
  public_scam_reports: Megaphone,
};

function RowIcon({ row }: { row: Row }) {
  const size = 16;
  if (row.kind === "tool" && row.tool) {
    const Icon = toolIcons[row.tool];
    return <Icon size={size} />;
  }
  const icons = {
    received: Inbox,
    redacted: ShieldOff,
    classifier: Sigma,
    plan: Brain,
    replan: Repeat,
    verdict: Gavel,
    waiting: Loader2,
    tool: ScanSearch,
  } as const;
  const Icon = icons[row.kind];
  return <Icon size={size} className={row.kind === "waiting" ? "cx-spin" : undefined} />;
}

function Highlighted({ text }: { text: string }) {
  return (
    <>
      {splitRedacted(text).map((part, i) =>
        isRedactionTag(part) ? (
          <mark key={i} className="cx-tag">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/** The live feed of what the backend is doing for one message. */
export function BehindTheScenes({ message, poll }: { message?: InboxItem; poll?: ResultPoll }) {
  const [privacy, setPrivacy] = useState<PrivacyView>();
  const steps = poll?.trail.length ?? 0;
  const id = message?.message_id;

  // The privacy log grows as tools run: refresh it whenever a new step lands.
  useEffect(() => {
    if (!id) return;
    let active = true;
    getPrivacy(id)
      .then((view) => active && setPrivacy(view))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [id, steps, poll?.status, poll?.mode]);

  useEffect(() => setPrivacy(undefined), [id]);

  const rows = buildRows(message, poll, privacy);
  const elapsed = elapsedSeconds(poll);

  return (
    <section className="cx-feed" aria-label="Behind the scenes">
      <header className="cx-feed-head">
        <div>
          <p className="cx-eyebrow">Behind the scenes</p>
          <h2>{poll?.mode === "recovery" ? "Recovery re-plan" : "How SentinelAI checked it"}</h2>
        </div>
        <span className={`cx-badge ${poll?.status === "done" ? "cx-badge-done" : "cx-badge-live"}`}>
          {poll?.status === "done" ? (
            <>Done{elapsed ? ` · ${elapsed}` : ""}</>
          ) : poll ? (
            <>
              <CircleDot size={12} className="cx-pulse" aria-hidden="true" /> Live
            </>
          ) : (
            "Idle"
          )}
        </span>
      </header>

      {!message && <p className="cx-muted cx-pad">The agent’s steps appear here, one at a time, as it works.</p>}

      <ol className="cx-timeline" aria-live="polite">
        {rows.map((row) => (
          <li key={row.key} className={`cx-row cx-row-${row.kind}`}>
            <span className="cx-node" aria-hidden="true">
              <RowIcon row={row} />
            </span>
            <div className="cx-row-body">
              <div className="cx-row-top">
                <strong>{row.title}</strong>
                {row.service && row.service !== "local" && <span className="cx-chip">{row.service}</span>}
                {row.service === "local" && <span className="cx-chip cx-chip-quiet">on our server</span>}
                {row.meta && <span className="cx-meta">{row.meta}</span>}
              </div>
              {row.detail && <p>{row.detail}</p>}
              {row.kind === "redacted" && row.raw && row.redacted && (
                <div className="cx-compare">
                  <div>
                    <span className="cx-eyebrow">Original</span>
                    <p className="cx-mono">{row.raw}</p>
                  </div>
                  <div>
                    <span className="cx-eyebrow">What the AI saw</span>
                    <p className="cx-mono">
                      <Highlighted text={row.redacted} />
                    </p>
                  </div>
                </div>
              )}
              {row.why && <p className="cx-why">Why: {row.why}</p>}
            </div>
          </li>
        ))}
      </ol>

      {privacy && privacy.recipients.length > 0 && (
        <details className="cx-privacy">
          <summary>
            <ListChecks size={15} aria-hidden="true" /> What each model and tool received ({privacy.recipients.length})
          </summary>
          <ul>
            {privacy.recipients.map((r, i) => (
              <li key={`${r.recipient}-${i}`}>
                <strong>{recipientLabel(r)}</strong>
                <span className="cx-muted"> · {r.received_fields.map(fieldLabel).join(", ") || "nothing personal"}</span>
              </li>
            ))}
          </ul>
          {privacy.never_sent.length > 0 && (
            <p className="cx-muted">Never sent anywhere: {privacy.never_sent.map(fieldLabel).join(", ")}.</p>
          )}
        </details>
      )}
    </section>
  );
}
