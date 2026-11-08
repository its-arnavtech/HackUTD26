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
import type {
  AgentResult,
  Campaign,
  DemoMessage,
  MetricRow,
  TrailEntry,
  Transaction,
  Verdict,
} from "./types";
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
export function MessageBubble({
  message,
  small = false,
}: {
  message: DemoMessage;
  small?: boolean;
}) {
  return (
    <div className={`message-bubble ${small ? "small-message" : ""}`}>
      <p className="eyebrow">Text claiming to be {message.brand}</p>
      <p className="message-text">
        {small
          ? "“Your account will be locked in 2 hours. Verify now…”"
          : message.text
              .split(/(<URL_\d+>)/g)
              .map((part, i) =>
                part.startsWith("<URL_") ? (
                  <PrivacyChip key={i} token={part} />
                ) : (
                  part
                ),
              )}
      </p>
      {!small && (
        <span className="metadata">
          Authored demo text · {time(message.received_at)}
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
export function VerdictBadge({
  verdict,
  large = false,
}: {
  verdict: Verdict;
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
      <span>{verdictLabels[verdict]}</span>
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
        {result.evidence.length} checks complete
      </div>
      <VerdictBadge verdict={result.verdict} large />
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
        <details>
          <summary>Why we checked</summary>
          <p>{entry.why}</p>
          {entry.kind === "tool" && (
            <span className="metadata">Completed in {entry.ms} ms</span>
          )}
        </details>
      </div>
    </article>
  );
}
export function WasThisYouCard({
  transaction,
  onAnswer,
  busy = false,
}: {
  transaction: Transaction;
  onAnswer: (wasMe: boolean) => void;
  busy?: boolean;
}) {
  return (
    <article className="was-you-card">
      <div className="transaction-icon">
        <WalletCards size={27} />
      </div>
      <p className="eyebrow">Transfer to a new payee</p>
      <p className="transfer-amount">
        ${transaction.amount.toLocaleString("en-US")}
      </p>
      <p>{transaction.payee}</p>
      <div className="transaction-details">
        <span>Today, {time(transaction.at)}</span>
        <span>{transaction.minutes_after_message} minutes after the text</span>
      </div>
      <p className="was-you-question">Was this you?</p>
      <ActionButton onClick={() => onAnswer(false)} disabled={busy}>
        No, I don’t recognize this
      </ActionButton>
      <ActionButton secondary onClick={() => onAnswer(true)} disabled={busy}>
        Yes, I made this transfer
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
        <span className="eyebrow">Fake billing</span>
      </div>
      <h2>
        A familiar name.
        <br />A false deadline.
      </h2>
      <p>
        Texts pretending to be {campaign.brand}, asking for an urgent payment.
      </p>
      <div className="campaign-number">
        <strong>{campaign.count_today}</strong>
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
const percent = (n: number) => `${(n * 100).toFixed(1)}%`;
export function MetricTable({ rows }: { rows: MetricRow[] }) {
  return (
    <div className="table-scroll">
      <table className="metric-table">
        <caption>
          Illustrative category scores. Each model is compared on the same
          held-out fixture.
        </caption>
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
              <th scope="row">{row.category}</th>
              <td>{row.support}</td>
              {(["baseline", "sentinel"] as const).flatMap((model) =>
                (["precision", "recall", "f1"] as const).map((measure) => (
                  <td
                    key={model + measure}
                    className={model === "sentinel" ? "our-column" : ""}
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
  title,
  description,
}: {
  error?: boolean;
  onRetry?: () => void;
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
          {error ? "Try the check again" : "Try a demo message"}
        </ActionButton>
      )}
    </div>
  );
}
export function PrivacyFootnote() {
  return (
    <Link to="/privacy" className="privacy-footnote">
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
