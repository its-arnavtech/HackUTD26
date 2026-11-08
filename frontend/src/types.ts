// Mirrors backend/app/contracts.py exactly (DATA_SPEC.md).
// Shared file: change it only in a `[contracts] ...` PR, together with contracts.py.

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type Verdict = "likely_scam" | "unsure" | "likely_safe";
export type ConfidenceWords = "very likely" | "likely" | "not sure";
export type Action =
  | "block_sender"
  | "report_spam"
  | "call_number_on_card"
  | "open_official_app"
  | "freeze_card"
  | "change_password"
  | "alert_trusted_contact"
  | "ignore";
export type SenderType = "short_code" | "long_code" | "alphanumeric" | "email" | "unknown";
export type TrailKind = "plan" | "tool" | "replan" | "verdict";
export type SourceType = "official" | "government" | "news" | "security_vendor" | "community";
export type DemoMode = "live" | "record" | "replay";
export type AgentMode = "check" | "recovery";
export type JobStatus = "queued" | "running" | "done";
export type ToolName =
  | "check_link"
  | "check_sender"
  | "match_campaign"
  | "nessie_recent_activity"
  | "nessie_bill_status"
  | "public_scam_reports";
export type MessageSource = "generated" | "handwritten" | "public" | "scenario" | "authored";
export type ActivityType = "transfer" | "purchase" | "bill" | "deposit" | "withdrawal";

/** ISO 8601 date-time string. */
export type DateTime = string;
/** ISO 8601 date string (YYYY-MM-DD). */
export type DateString = string;

// ---------------------------------------------------------------------------
// Messages and redaction (DATA_SPEC 2, 5)
// ---------------------------------------------------------------------------

export interface MessageIn {
  text: string;
  sender: string;
  received_at: DateTime;
}

export interface Message {
  message_id: string;
  text: string;
  sender: string;
  received_at?: DateTime | null;
  is_scam?: boolean | null;
  category?: string | null;
  source?: MessageSource;
  prompt_set?: string | null;
}

export interface RedactionCounts {
  PERSON: number;
  PHONE: number;
  ACCOUNT_DIGITS: number;
  ADDRESS: number;
  EMAIL: number;
}

export interface RedactionReport {
  counts: RedactionCounts;
  kept: string[];
}

export interface RedactedMessage {
  text_redacted: string;
  report: RedactionReport;
  raw_urls: string[];
}

// ---------------------------------------------------------------------------
// Nemotron input (DATA_SPEC 3.1)
// ---------------------------------------------------------------------------

export interface SenderInfo {
  type: SenderType;
  value: string;
  claimed_brand?: string | null;
}

export interface UrlInfo {
  id: string;
  registered_domain: string;
  is_shortener: boolean;
  brand_term_in_domain?: string | null;
  is_official_brand_domain: boolean;
}

export interface Features {
  urgency_deadline?: string | null;
  threat?: string | null;
  requested_action?: string | null;
  asks_for: string[];
  money_amount_claimed?: number | null;
}

export interface ClassifierOutput {
  category: string;
  score: number;
  top3: [string, number][];
  baseline_score?: number | null;
}

export interface CustomerContext {
  linked_bank: boolean;
  linked_institutions: string[];
}

export interface AgentInput {
  message_id: string;
  mode: AgentMode;
  received_at: DateTime;
  since?: DateTime | null;
  sender: SenderInfo;
  text_redacted: string;
  urls: UrlInfo[];
  features: Features;
  classifier: ClassifierOutput;
  customer_context: CustomerContext;
}

// ---------------------------------------------------------------------------
// Tool args and results (DATA_SPEC 3.2)
// ---------------------------------------------------------------------------

export interface CheckLinkArgs {
  url_id: string;
}

export interface CheckLinkResult {
  domain: string;
  domain_age_days?: number | null;
  on_blocklist: boolean;
  lookalike_of?: string | null;
  final_redirect_domain?: string | null;
  signals: string[];
}

export interface CheckSenderArgs {
  claimed_brand: string;
}

export interface CheckSenderResult {
  sender_type: SenderType;
  matches_official_channel: boolean;
  official_channels_known: boolean;
  note: string;
}

export interface MatchCampaignArgs {
  message_id: string;
}

export interface MatchCampaignResult {
  campaign_id?: string | null;
  similar_last_24h: number;
  first_seen?: DateTime | null;
  similarity: number;
  template?: string | null;
}

/** Exactly one of `days` or `since`. */
export interface NessieRecentActivityArgs {
  days?: number | null;
  since?: DateTime | null;
}

export interface FlaggedItem {
  ref: string;
  type: ActivityType;
  amount: number;
  new_payee: boolean;
  minutes_after_message?: number | null;
  reason: string;
}

export interface NessieRecentActivityResult {
  accounts_checked: number;
  items_checked: number;
  flagged: FlaggedItem[];
}

export interface NessieBillStatusArgs {
  payee: string;
}

export interface NessieBillStatusResult {
  found: boolean;
  last_status?: string | null;
  last_payment_date?: DateString | null;
  amount_due_now?: number | null;
  recurring?: boolean | null;
}

// ---------------------------------------------------------------------------
// Gemini (DATA_SPEC 4)
// ---------------------------------------------------------------------------

export interface GeminiInput {
  claimed_brand: string;
  scam_category: string;
  link_domain?: string | null;
  lure_phrase: string;
}

export interface PublicReport {
  source_type: SourceType;
  publisher: string;
  url: string;
  date?: DateString | null;
  claim: string;
  stale: boolean;
}

export interface BrandGuidance {
  never_asks_by_text: string[];
  source_url: string;
}

export interface GeminiOutput {
  reports_found: number;
  reports: PublicReport[];
  brand_guidance?: BrandGuidance | null;
  domain_reported: boolean;
  recovery_steps_source?: string | null;
  newest_report_age_days?: number | null;
}

export interface PublicScamReportsArgs {
  claimed_brand: string;
  scam_category: string;
  link_domain?: string | null;
}

export type PublicScamReportsResult = GeminiOutput;

// ---------------------------------------------------------------------------
// Agent output and trail (DATA_SPEC 3.3, 3.4)
// ---------------------------------------------------------------------------

export interface Evidence {
  tool: ToolName;
  finding: string;
}

export interface AgentResult {
  plan: ToolName[];
  verdict: Verdict;
  confidence_words: ConfidenceWords;
  reason: string;
  evidence: Evidence[];
  /** At most 3. */
  actions: Action[];
  was_this_you: string[];
  replan: boolean;
}

export interface TrailEntry {
  step: number;
  kind: TrailKind;
  tool?: ToolName | null;
  why?: string | null;
  finding?: string | null;
  ms?: number | null;
  at: DateTime;
}

// ---------------------------------------------------------------------------
// API views (POC_MVP 7.1)
// ---------------------------------------------------------------------------

export interface InboxItem {
  message_id: string;
  sender: string;
  text: string;
  received_at: DateTime;
  status: JobStatus;
  verdict?: Verdict | null;
  confidence_words?: ConfidenceWords | null;
  source: MessageSource;
}

export interface WasThisYouItem {
  ref: string;
  type: ActivityType;
  amount: number;
  payee: string;
  at: DateTime;
}

export interface ResultPoll {
  message_id: string;
  status: JobStatus;
  mode: AgentMode;
  trail: TrailEntry[];
  result?: AgentResult | null;
  was_this_you_items: WasThisYouItem[];
}

export interface PostMessageResponse {
  message_id: string;
}

export interface ClickedResponse {
  message_id: string;
  status: JobStatus;
  mode: AgentMode;
}

export interface ConfirmRequest {
  was_me: boolean;
}

export interface ConfirmResponse {
  ref: string;
  was_me: boolean;
  recorded: boolean;
}

export interface ActionRequest {
  message_id: string;
  action: Action;
}

export interface ActionResponse {
  message_id: string;
  action: Action;
  status: "simulated";
  note: string;
}

export interface DemoResetResponse {
  ok: boolean;
  inbox_count: number;
}

// ---------------------------------------------------------------------------
// Privacy view
// ---------------------------------------------------------------------------

export interface PrivacyRecipient {
  recipient: string;
  kind: "model" | "tool" | "local";
  received_fields: string[];
  payload: Record<string, unknown>;
  at?: DateTime | null;
}

export interface PrivacyView {
  message_id: string;
  redaction: RedactionReport;
  recipients: PrivacyRecipient[];
  never_sent: string[];
}

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export interface Campaign {
  campaign_id: string;
  claimed_brand?: string | null;
  category: string;
  domain_pattern?: string | null;
  count_total: number;
  count_last_24h: number;
  first_seen: DateTime;
  last_seen: DateTime;
  template: string;
  redacted_example: string;
  linked_message_ids: string[];
}

// ---------------------------------------------------------------------------
// Metrics (POC_MVP 7.5, DATA_SPEC 7)
// ---------------------------------------------------------------------------

export interface Scores {
  precision: number;
  recall: number;
  f1: number;
}

export interface CategoryMetrics {
  category: string;
  support: number;
  ours: Scores;
  baseline: Scores;
}

export interface OursVsBaseline {
  ours: number;
  baseline: number;
}

export interface RedactionCost {
  macro_f1_unredacted: number;
  macro_f1_redacted: number;
}

export interface AgentSample {
  n: number;
  share_correct: number;
  share_unsure: number;
}

export interface PublicSetMetrics {
  dataset: string;
  n: number;
  spam_recall: OursVsBaseline;
  false_positive_rate: OursVsBaseline;
}

export interface Metrics {
  generated_at: DateTime;
  split: "test";
  n_test: number;
  categories: CategoryMetrics[];
  macro_f1: OursVsBaseline;
  false_positive_rate: OursVsBaseline;
  public_set?: PublicSetMetrics | null;
  redaction_cost?: RedactionCost | null;
  agent_sample?: AgentSample | null;
}

export interface BaselineCategoryMetrics {
  category: string;
  support: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface BaselineMetrics {
  generated_at: DateTime;
  split: "test";
  n_test: number;
  categories: BaselineCategoryMetrics[];
  macro_f1: number;
  false_positive_rate: number;
}

// ---------------------------------------------------------------------------
// Authentication and audit (DATA_SPEC section 8, L13). Only used when auth is on.
// Tokens never appear here: they travel in HttpOnly cookies the page can't read.
// ---------------------------------------------------------------------------

export type Role = "customer" | "admin";

export interface PasswordLoginRequest {
  username: string;
  password: string;
}

export interface TotpRequest {
  code: string;
}

export interface LoginStep {
  signed_in: boolean;
  mfa_required?: boolean;
}

export interface Me {
  user_id: string;
  username: string;
  display_name: string;
  role: Role;
  passkeys: number;
}

export interface AuditEventView {
  id: number;
  ts: DateTime;
  event: string;
  actor: string;
  target: string;
  outcome: "success" | "failure" | "denied";
  ip_hash: string;
  details?: Record<string, string | number | boolean>;
}

export interface AuditView {
  chain_intact: boolean;
  first_broken_id?: number | null;
  events: AuditEventView[];
}
