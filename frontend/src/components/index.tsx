import { type ButtonHTMLAttributes, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Ban,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  CreditCard,
  Fingerprint,
  Link2,
  LockKeyhole,
  ScanLine,
  Signal,
  Sparkles,
  Users,
  WalletCards,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { Failure } from "../api";
import type {
  ActivityType,
  AgentResult,
  Campaign,
  CategoryMetrics,
  ConfidenceWords,
  TrailEntry,
  Verdict,
  WasThisYouItem,
} from "../types";
const time = (value: string) =>
  new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
  }).format(new Date(value));
const shortDate = (value: string) =>
  new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    timeZone: "America/Chicago",
  }).format(new Date(value));
export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>
        Sentinel<span className="brand-ai">AI</span>
      </span>
    </span>
  );
}
export function PhoneFrame({
  children,
  label = "SentinelAI preview",
  back,
  backLabel = "Inbox",
  compact = false,
}: {
  children: ReactNode;
  label?: string;
  back?: string;
  backLabel?: string;
  compact?: boolean;
}) {
  return (
    <section
      className={`phone-frame ${compact ? "gallery-phone" : ""}`}
      aria-label={label}
    >
      <div className="status-bar" aria-hidden="true">
        <span>9:41</span>
        <span className="phone-island" />
        <span className="status-icons">
          <Signal size={16} />
          <span className="battery" />
        </span>
      </div>
      <header className="phone-header">
        <Brand />
        <LockKeyhole size={18} aria-label="Privacy first" />
      </header>
      <div
        className="phone-scroll"
        tabIndex={0}
        role="region"
        aria-label="Scrollable screen content"
      >
        {back && (
          <Link to={back} className="back-link">
            <ArrowLeft size={17} />
            {backLabel}
          </Link>
        )}
        {children}
      </div>
      <div className="phone-bottom" aria-hidden="true">
        <span />
      </div>
    </section>
  );
}
export function PageTitle({
  eyebrow,
  children,
  description,
}: {
  eyebrow?: string;
  children: ReactNode;
  description?: string;
}) {
  return (
    <div className="page-title">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1>{children}</h1>
      {description && <p>{description}</p>}
    </div>
  );
}
export const excerpt = (text: string, max = 70) =>
  text.length <= max ? text : `${text.slice(0, max).replace(/\s+\S*$/, "")}…`;
/** `text` must already be redacted: placeholder tokens render as privacy chips. */
export function MessageBubble({
  text,
  claimedBrand,
  receivedAt,
  small = false,
}: {
  text: string;
  claimedBrand?: string | null;
  receivedAt?: string | null;
  small?: boolean;
}) {
  return (
    <div className={`message-bubble ${small ? "small-message" : ""}`}>
      <p className="eyebrow">
        {claimedBrand ? `Text claiming to be ${claimedBrand}` : "The text"}
      </p>
      <p className="message-text">
        {small
          ? `“${excerpt(text)}”`
          : text
              .split(/(<[A-Z][A-Z0-9_]*>)/g)
              .map((part, i) =>
                /^<[A-Z][A-Z0-9_]*>$/.test(part) ? (
                  <PrivacyChip key={i} token={part} />
                ) : (
                  part
                ),
              )}
      </p>
      {!small && receivedAt && (
        <span className="metadata">
          Authored demo text · {time(receivedAt)}
        </span>
      )}
    </div>
  );
}
const verdictLabels: Record<Verdict, string> = {
  likely_scam: "Very likely a scam",
  unsure: "We’re not sure",
  likely_safe: "Likely safe",
};
/** POC_MVP 4.4 wording, with the confidence in words. Never stronger than "Likely safe". */
export function verdictLabel(verdict: Verdict, confidence?: ConfidenceWords | null) {
  if (verdict === "likely_scam" && confidence === "likely") return "Likely a scam";
  return verdictLabels[verdict];
}
export function VerdictBadge({
  verdict,
  confidence,
  large = false,
}: {
  verdict: Verdict;
  confidence?: ConfidenceWords | null;
  large?: boolean;
}) {
  const Icon =
    verdict === "likely_scam"
      ? AlertTriangle
      : verdict === "unsure"
        ? CircleHelp
        : CheckCircle2;
  return (
    <span className={`verdict-badge ${verdict} ${large ? "large-badge" : ""}`}>
      <Icon size={large ? 23 : 17} />
      <span>{verdictLabel(verdict, confidence)}</span>
    </span>
  );
}
export function ActionButton({
  children,
  secondary = false,
  icon,
  arrow = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  secondary?: boolean;
  icon?: ReactNode;
  arrow?: boolean;
}) {
  return (
    <button
      {...props}
      className={`action-button ${secondary ? "action-secondary" : ""} ${props.className || ""}`}
    >
      {icon}
      {children}
      {arrow && <ArrowRight size={19} />}
    </button>
  );
}
export function ResultCard({
  result,
  activity,
  nextStep,
  onPrimary,
  onTrail,
  busy = false,
  primaryLabel,
  officialAction = false,
}: {
  result: AgentResult;
  activity: string;
  nextStep: string;
  onPrimary: () => void;
  onTrail: () => void;
  busy?: boolean;
  primaryLabel?: string;
  officialAction?: boolean;
}) {
  const scam = result.verdict === "likely_scam";
  return (
    <article className={`result-card verdict-${result.verdict}`}>
      <div className="result-topline">
        <span className="status-dot" />
        {result.evidence.length} {result.evidence.length === 1 ? "check" : "checks"} complete
      </div>
      <VerdictBadge verdict={result.verdict} confidence={result.confidence_words} large />
      <p className="result-reason">{result.reason}</p>
      <div className="evidence-summary">
        <WalletCards size={22} />
        <p>{activity}</p>
      </div>
      <div className="next-step">
        <p className="eyebrow">Your next step</p>
        <p>{nextStep}</p>
      </div>
      <ActionButton
        onClick={onPrimary}
        disabled={busy}
        icon={
          scam && !officialAction ? (
            <Ban size={20} />
          ) : (
            <WalletCards size={20} />
          )
        }
        arrow
      >
        {busy
          ? "One moment…"
          : primaryLabel ||
            (scam ? "Block this sender" : "Use the official app")}
      </ActionButton>
      <button className="row-link" onClick={onTrail}>
        How we checked
        <ChevronRight size={19} />
      </button>
    </article>
  );
}
export function PrivacyChip({ token }: { token: string }) {
  return <span className="privacy-chip">{token}</span>;
}
const toolLabels: Record<string, string> = {
  check_link: "The link",
  check_sender: "The sender",
  nessie_recent_activity: "Recent activity",
  match_campaign: "Similar messages",
  nessie_bill_status: "Your bill",
  public_scam_reports: "Public reports",
};
export function TrailStep({
  entry,
  index,
  animate = true,
}: {
  entry: TrailEntry;
  index: number;
  animate?: boolean;
}) {
  return (
    <article
      className={`trail-step ${entry.kind} ${animate ? "trail-enter" : ""}`}
      style={{ animationDelay: `${index * 130}ms` }}
    >
      <span className="trail-node">
        {entry.kind === "plan" ? (
          <ScanLine size={18} />
        ) : entry.kind === "replan" ? (
          <Sparkles size={18} />
        ) : (
          <Check size={17} />
        )}
      </span>
      <div>
        <p className="eyebrow">
          {entry.kind === "plan"
            ? "The plan"
            : entry.kind === "replan"
              ? "A new plan"
              : entry.kind === "verdict"
                ? "The result"
                : toolLabels[entry.tool || ""]}
        </p>
        <p className="trail-finding">{entry.finding}</p>
        {entry.why && (
          <details>
            <summary>Why we checked</summary>
            <p>{entry.why}</p>
            {entry.kind === "tool" && entry.ms != null && (
              <span className="metadata">Completed in {entry.ms} ms</span>
            )}
          </details>
        )}
      </div>
    </article>
  );
}
const activityLabels: Record<ActivityType, { eyebrow: string; noun: string }> =
  {
    transfer: { eyebrow: "A transfer", noun: "transfer" },
    purchase: { eyebrow: "A purchase", noun: "purchase" },
    bill: { eyebrow: "A bill payment", noun: "payment" },
    deposit: { eyebrow: "A deposit", noun: "deposit" },
    withdrawal: { eyebrow: "A withdrawal", noun: "withdrawal" },
  };
export function WasThisYouCard({
  item,
  minutesAfterMessage,
  onAnswer,
  busy = false,
}: {
  item: WasThisYouItem;
  minutesAfterMessage?: number | null;
  onAnswer: (wasMe: boolean) => void;
  busy?: boolean;
}) {
  const label = activityLabels[item.type];
  return (
    <article className="was-you-card">
      <div className="transaction-icon">
        <WalletCards size={27} />
      </div>
      <p className="eyebrow">{label.eyebrow}</p>
      <p className="transfer-amount">${item.amount.toLocaleString("en-US")}</p>
      <p>{item.payee}</p>
      <div className="transaction-details">
        <span>Today, {time(item.at)}</span>
        {minutesAfterMessage != null && (
          <span>{minutesAfterMessage} minutes after the text</span>
        )}
      </div>
      <p className="was-you-question">Was this you?</p>
      <ActionButton onClick={() => onAnswer(false)} disabled={busy}>
        No, I don’t recognize this
      </ActionButton>
      <ActionButton secondary onClick={() => onAnswer(true)} disabled={busy}>
        Yes, I made this {label.noun}
      </ActionButton>
    </article>
  );
}
export function ChecklistItem({
  label,
  detail,
  checked,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className={`checklist-item ${checked ? "is-checked" : ""}`}>
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span className="check-box" aria-hidden="true">
        {checked && <Check size={17} />}
      </span>
      <span>
        <strong>{label}</strong>
        <span className="checklist-detail">{detail}</span>
      </span>
    </label>
  );
}
export function CampaignCard({
  campaign,
  onOpen,
}: {
  campaign: Campaign;
  onOpen?: () => void;
}) {
  return (
    <article className="campaign-card">
      <div className="campaign-top">
        <span className="circle-icon">
          <Users size={24} />
        </span>
        <span className="eyebrow">{categoryLabel(campaign.category)}</span>
      </div>
      <h2>
        A familiar name.
        <br />A false deadline.
      </h2>
      <p>
        Texts pretending to be {campaign.claimed_brand || "a familiar company"},
        asking you to act fast.
      </p>
      <div className="campaign-number">
        <strong>{campaign.count_last_24h}</strong>
        <span>similar texts today</span>
      </div>
      <p className="metadata">
        First seen {shortDate(campaign.first_seen)} · Anonymized patterns
      </p>
      {onOpen && (
        <button className="row-link" onClick={onOpen}>
          View the pattern
          <ChevronRight size={18} />
        </button>
      )}
    </article>
  );
}
const categoryLabels: Record<string, string> = {
  billing_scam: "Fake billing",
  bank_impersonation: "Bank impersonation",
  delivery_scam: "Fake delivery",
  account_security: "Account security",
  toll_government: "Toll or government",
  prize_refund: "Prize or refund",
  job_offer: "Job offer",
  conversation_lure: "Conversation lure",
  legit: "Legitimate messages",
  legitimate: "Legitimate messages",
};
export const categoryLabel = (category: string) =>
  categoryLabels[category] ||
  category.charAt(0).toUpperCase() + category.slice(1).replace(/_/g, " ");
const percent = (n: number) => `${(n * 100).toFixed(1)}%`;
/** Judge-facing only: the one place percentages are allowed. */
export function MetricTable({
  rows,
  caption = "Category scores. Each model is compared on the same held-out test split.",
}: {
  rows: CategoryMetrics[];
  caption?: string;
}) {
  return (
    <div className="table-scroll">
      <table className="metric-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th rowSpan={2}>Message category</th>
            <th rowSpan={2}>Samples</th>
            <th colSpan={3}>Simple baseline</th>
            <th colSpan={3} className="our-column">
              SentinelAI
            </th>
          </tr>
          <tr>
            {["Precision", "Recall", "F1", "Precision", "Recall", "F1"].map(
              (x, i) => (
                <th key={i} className={i >= 3 ? "our-column" : ""}>
                  {x}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.category}>
              <th scope="row">{categoryLabel(row.category)}</th>
              <td>{row.support}</td>
              {(["baseline", "ours"] as const).flatMap((model) =>
                (["precision", "recall", "f1"] as const).map((measure) => (
                  <td
                    key={model + measure}
                    className={model === "ours" ? "our-column" : ""}
                  >
                    {percent(row[model][measure])}
                  </td>
                )),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function EmptyState({
  error = false,
  onRetry,
  retryLabel,
  title,
  description,
}: {
  error?: boolean;
  onRetry?: () => void;
  retryLabel?: string;
  title?: string;
  description?: string;
}) {
  return (
    <div className="empty-state">
      <span className="large-circle">
        {error ? <CircleHelp size={36} /> : <CheckCircle2 size={36} />}
      </span>
      <h2>
        {title ||
          (error
            ? "We couldn’t finish this check."
            : "A little breathing room.")}
      </h2>
      <p>
        {description ||
          (error
            ? "We haven’t reached a verdict. Don’t use the link while you wait."
            : "There are no messages to check right now. New messages will appear here.")}
      </p>
      {onRetry && (
        <ActionButton
          onClick={onRetry}
          icon={error ? <ScanLine size={20} /> : <Link2 size={20} />}
        >
          {retryLabel ?? (error ? "Try the check again" : "Try a demo message")}
        </ActionButton>
      )}
    </div>
  );
}

/** Why a screen couldn't load: what the API said, or that it ran too long. */
export type LoadFailureKind = Failure | "slow";

const failureCopy: Partial<Record<LoadFailureKind, { title: string; description: string }>> = {
  offline: {
    title: "We can’t reach SentinelAI right now.",
    description: "Nothing was changed. Try again in a moment.",
  },
  not_found: {
    title: "We couldn’t find this message.",
    description: "It may have been cleared when the demo was reset. Nothing was changed.",
  },
  not_wired: {
    title: "This part isn’t connected yet.",
    description: "Its live service hasn’t been switched on for this demo. Nothing was changed.",
  },
  slow: {
    title: "This check is taking longer than usual.",
    description: "We haven’t reached a verdict yet. Don’t use the link while you wait.",
  },
};

/**
 * The error state every API-backed screen shares. Offline, not found, not connected yet and slow
 * have their own wording; anything else uses the screen's `title` and `description`.
 */
export function LoadFailure({
  failure,
  title,
  description,
  onRetry,
  retryLabel = "Try again",
}: {
  failure?: LoadFailureKind;
  title?: string;
  description?: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  const copy = failure ? failureCopy[failure] : undefined;
  const missing = failure === "not_found";
  return (
    <>
      <EmptyState
        error
        title={copy?.title ?? title}
        description={copy?.description ?? description}
        onRetry={missing ? undefined : onRetry}
        retryLabel={retryLabel}
      />
      {missing && (
        <Link className="row-link" to="/inbox">
          Back to your messages
          <ChevronRight size={18} />
        </Link>
      )}
    </>
  );
}
export function PrivacyFootnote({ messageId }: { messageId?: string }) {
  return (
    <Link to={messageId ? `/privacy/${encodeURIComponent(messageId)}` : "/privacy"} className="privacy-footnote">
      <LockKeyhole size={14} />
      Personal details hidden before checks
    </Link>
  );
}
export function Notice({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose?: () => void;
}) {
  return (
    <div className="notice" role="status">
      <CheckCircle2 size={20} />
      <span>{children}</span>
      {onClose && (
        <button onClick={onClose} aria-label="Dismiss message">
          <X size={18} />
        </button>
      )}
    </div>
  );
}
export const Icons = { CreditCard, Fingerprint, Clock3 };
