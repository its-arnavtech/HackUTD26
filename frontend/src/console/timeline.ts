// Turns one message's live poll + privacy log into the "behind the scenes" rows (L14).
// Pure functions: no fetching, no React, so they are easy to test.
import { categoryLabel } from "../components";
import { redactedText } from "../present";
import type { InboxItem, PrivacyView, ResultPoll, ToolName, TrailEntry } from "../types";

export type RowKind = "received" | "redacted" | "classifier" | "plan" | "tool" | "replan" | "verdict" | "waiting";

export interface Row {
  key: string;
  kind: RowKind;
  title: string;
  /** Main line: what was found or what happened. */
  detail?: string;
  /** Why the agent took this step. */
  why?: string;
  /** Right-aligned meta: timing, score, service. */
  meta?: string;
  /** For the redaction row: raw text vs. what the AI saw. */
  raw?: string;
  redacted?: string;
  /** Which outside service, if any, this step called. */
  service?: "Nessie (Capital One)" | "Gemini" | "RDAP" | "Nemotron" | "local";
  tool?: ToolName;
}

export const toolTitles: Record<ToolName, string> = {
  check_link: "Link check",
  check_sender: "Sender check",
  match_campaign: "Scam-campaign match",
  nessie_recent_activity: "Bank activity",
  nessie_bill_status: "Bill status",
  public_scam_reports: "Public scam reports",
  check_request: "What it asks you to do",
};

const toolServices: Partial<Record<ToolName, Row["service"]>> = {
  check_link: "RDAP",
  nessie_recent_activity: "Nessie (Capital One)",
  nessie_bill_status: "Nessie (Capital One)",
  public_scam_reports: "Gemini",
  check_sender: "local",
  match_campaign: "local",
  check_request: "local",
};

const planTools = (entry: TrailEntry): string | undefined => entry.finding ?? undefined;

function trailRow(entry: TrailEntry): Row {
  const key = `trail-${entry.step}-${entry.kind}`;
  const meta = entry.ms != null ? `${(entry.ms / 1000).toFixed(entry.ms < 1000 ? 2 : 1)} s` : undefined;
  switch (entry.kind) {
    case "plan":
      return { key, kind: "plan", title: "Agent plan", detail: planTools(entry), why: entry.why ?? undefined, meta, service: "Nemotron" };
    case "replan":
      return { key, kind: "replan", title: "New plan", detail: entry.finding ?? undefined, why: entry.why ?? undefined, meta, service: "Nemotron" };
    case "verdict":
      return { key, kind: "verdict", title: "Verdict", detail: entry.finding ?? undefined, why: entry.why ?? undefined, meta };
    default: {
      const tool = entry.tool ?? undefined;
      return {
        key,
        kind: "tool",
        tool,
        title: tool ? toolTitles[tool] : "Check",
        detail: entry.finding ?? undefined,
        why: entry.why ?? undefined,
        meta,
        service: tool ? toolServices[tool] : undefined,
      };
    }
  }
}

/** The classifier's category and score, as the AI planner received them (from the privacy log). */
export function classifierLine(privacy?: PrivacyView): string | undefined {
  const planner = privacy?.recipients.find((r) => r.recipient === "nemotron");
  const value = planner?.payload?.classifier as { category?: string; score?: number; top_category?: string } | undefined;
  if (!value || typeof value !== "object") return undefined;
  const category = value.category ?? value.top_category;
  const score = typeof value.score === "number" ? value.score.toFixed(2) : undefined;
  if (!category && !score) return undefined;
  return [category ? categoryLabel(category) : undefined, score ? `score ${score}` : undefined].filter(Boolean).join(" · ");
}

export function buildRows(message?: InboxItem, poll?: ResultPoll, privacy?: PrivacyView): Row[] {
  const rows: Row[] = [];
  if (message) {
    rows.push({
      key: "received",
      kind: "received",
      title: message.source === "sms" ? "Text received by SMS" : "Message received",
      detail: message.sender === "unknown" ? "Forwarded text (sender not included)" : `From ${message.sender}`,
    });
  }
  const hidden = privacy ? redactedText(privacy) : undefined;
  if (message && hidden) {
    rows.push({
      key: "redacted",
      kind: "redacted",
      title: "Personal details hidden",
      detail: "Only this version reaches the classifier, the AI and every tool.",
      raw: message.text,
      redacted: hidden,
      service: "local",
    });
  }
  const classifier = classifierLine(privacy);
  if (classifier) rows.push({ key: "classifier", kind: "classifier", title: "Classifier", detail: classifier, service: "local" });
  for (const entry of poll?.trail ?? []) rows.push(trailRow(entry));
  if (poll && poll.status !== "done") {
    rows.push({ key: "waiting", kind: "waiting", title: poll.status === "queued" ? "Queued" : "Working…" });
  }
  return rows;
}

/** Total time from the first to the last trail entry, for the header ("6.2 s"). */
export function elapsedSeconds(poll?: ResultPoll): string | undefined {
  const trail = poll?.trail ?? [];
  if (trail.length < 2) return undefined;
  const ms = Date.parse(trail[trail.length - 1].at) - Date.parse(trail[0].at);
  return Number.isFinite(ms) && ms >= 0 ? `${(ms / 1000).toFixed(1)} s` : undefined;
}

/** Which tools this run used, in order, for "different plan per message" (NVIDIA). */
export const toolsUsed = (poll?: ResultPoll): ToolName[] =>
  (poll?.trail ?? []).flatMap((e) => (e.kind === "tool" && e.tool ? [e.tool] : []));
