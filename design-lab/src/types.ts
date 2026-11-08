export type Verdict = "likely_scam" | "unsure" | "likely_safe";
export type Action =
  | "block_sender"
  | "report_spam"
  | "call_number_on_card"
  | "open_official_app"
  | "freeze_card"
  | "change_password"
  | "alert_trusted_contact"
  | "ignore";
export type Tool =
  | "check_link"
  | "check_sender"
  | "match_campaign"
  | "nessie_recent_activity"
  | "nessie_bill_status"
  | "public_scam_reports";
/** DATA_SPEC 3.3, kept separate from UI presentation fields. */
export interface AgentResult {
  plan: Tool[];
  verdict: Verdict;
  confidence_words: "very likely" | "likely" | "not sure";
  reason: string;
  evidence: { tool: Tool; finding: string }[];
  actions: Action[];
  was_this_you: string[];
  replan: boolean;
}
/** DATA_SPEC 3.4. */
export interface TrailEntry {
  step: number;
  kind: "plan" | "tool" | "replan" | "verdict";
  tool?: Tool;
  why: string;
  finding: string;
  ms: number;
  at: string;
}
/** DATA_SPEC 5. */
export interface RedactionReport {
  counts: {
    PERSON: number;
    PHONE: number;
    ACCOUNT_DIGITS: number;
    ADDRESS: number;
    EMAIL: number;
  };
  kept: string[];
}
export type ScenarioId = "bank" | "recovery" | "billing";
export type ResultState = "scam" | "unsure" | "safe" | "mixed";
export interface DemoMessage {
  id: string;
  brand: string;
  text: string;
  received_at: string;
  status: "checking" | "done";
  verdict?: Verdict;
  authored: true;
  preview?: string;
}
export interface Scenario {
  id: ScenarioId;
  title: string;
  message: DemoMessage;
  result: AgentResult;
  trail: TrailEntry[];
  next_step: string;
  activity_summary: string;
  redaction: RedactionReport;
}
export interface PrivacyReport {
  redaction: RedactionReport;
  text_redacted: string;
  recipients: { name: string; received: string[]; never: string[] }[];
  stored: string[];
  session_only: string[];
}
export interface Transaction {
  ref: string;
  type: "transfer";
  amount: number;
  payee: string;
  at: string;
  minutes_after_message: number;
  new_payee: boolean;
}
export interface RecoveryItem {
  id: string;
  label: string;
  detail: string;
  action: Action;
}
export interface Campaign {
  id: string;
  brand: string;
  count_today: number;
  first_seen: string;
  template: string;
  example_redacted: string;
  message_ids: string[];
  reports: { publisher: string; claim: string; date: string }[];
}
export interface MetricRow {
  category: string;
  support: number;
  baseline: { precision: number; recall: number; f1: number };
  sentinel: { precision: number; recall: number; f1: number };
}
export interface Metrics {
  illustrative: true;
  rows: MetricRow[];
  false_positive_rate: { baseline: number; sentinel: number };
  redaction: { before: number; after: number };
  dataset: string;
  sample_size: number;
}
export interface ActionReceipt {
  action: Action;
  message_id: string;
  simulated: true;
  label: string;
}
