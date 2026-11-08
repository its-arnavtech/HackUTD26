import {
  campaigns,
  metrics,
  privacy,
  recoveryItems,
  scenarios,
  transaction,
  variants,
} from "./data/mocks";
import type {
  Action,
  ActionReceipt,
  DemoMessage,
  ResultState,
  Scenario,
  ScenarioId,
} from "./types";
const clone = <T>(data: T): T => structuredClone(data);
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
/** The only data-access boundary. Replace these methods with backend adapters at port time. */
export const api = {
  async getScenario(
    id: ScenarioId = "bank",
    state: ResultState = "scam",
  ): Promise<Scenario> {
    const value = clone(scenarios[id]);
    if (state !== "scam") {
      value.result = clone(variants[state]);
      value.message.verdict = value.result.verdict;
      value.activity_summary =
        state === "safe"
          ? "The notice matches an activity item we checked."
          : "We couldn’t confirm all the details.";
      value.next_step = "Use the official app to check for yourself.";
      value.trail = [
        {
          step: 1,
          kind: "plan",
          finding: "Compare the sender and message with known signals.",
          why: "We need evidence before reaching a verdict.",
          ms: 0,
          at: value.message.received_at,
        },
        ...value.result.evidence.map((e, i) => ({
          step: i + 2,
          kind: "tool" as const,
          tool: e.tool,
          finding: e.finding,
          why: "This check helps assess the message’s claim.",
          ms: 412,
          at: value.message.received_at,
        })),
        {
          step: value.result.evidence.length + 2,
          kind: "verdict",
          finding:
            value.result.verdict === "likely_safe"
              ? "Likely safe."
              : "We’re not sure.",
          why: value.result.reason,
          ms: 0,
          at: value.message.received_at,
        },
      ];
      if (state === "safe")
        value.message.text =
          "Capital One: a recent sign-in was recorded. Review it in the official app.";
      if (state === "unsure")
        value.message.text = "Capital One: please review your recent sign-in.";
    }
    if (state === "mixed")
      value.message.text = "Capital One: verify a recent sign-in: <URL_1>";
    if (
      sessionStorage.getItem("sentinel-linked") === "false" &&
      state === "scam"
    ) {
      value.result.plan = value.result.plan.filter(
        (t) => t !== "nessie_recent_activity" && t !== "nessie_bill_status",
      );
      value.result.evidence = value.result.evidence.filter(
        (e) =>
          e.tool !== "nessie_recent_activity" &&
          e.tool !== "nessie_bill_status",
      );
      value.trail = value.trail.filter(
        (e) =>
          e.tool !== "nessie_recent_activity" &&
          e.tool !== "nessie_bill_status",
      );
      value.activity_summary =
        id === "billing"
          ? "Bill status wasn’t checked. No account is linked."
          : "Bank activity wasn’t checked. No account is linked.";
      value.trail = value.trail.map((e) =>
        e.kind === "plan"
          ? {
              ...e,
              finding:
                id === "billing"
                  ? "Check similar messages and public guidance."
                  : "Check the link and sender.",
              why: "No bank account is linked.",
            }
          : e,
      );
    }
    return value;
  },
  async getInbox(): Promise<DemoMessage[]> {
    return clone([scenarios.bank.message, scenarios.billing.message]);
  },
  async getPrivacy(id: ScenarioId = "bank") {
    const value = clone(privacy);
    value.redaction = clone(scenarios[id].redaction);
    if (id === "billing") value.text_redacted = scenarios.billing.message.text;
    return value;
  },
  async getCampaigns() {
    return clone(campaigns);
  },
  async getMetrics(dataset: "synthetic" | "public" = "synthetic") {
    const value = clone(metrics);
    if (dataset === "public") {
      value.dataset = "Public SMS set · illustrative fixture";
      value.sample_size = 200;
      value.rows = value.rows.slice(0, 2).map((row, i) => ({
        ...row,
        category: i ? "Legitimate messages" : "Spam messages",
        support: 100,
      }));
    }
    return value;
  },
  async getRecovery() {
    return {
      linked: sessionStorage.getItem("sentinel-linked") !== "false",
      transaction: clone(transaction),
      items: clone(recoveryItems),
    };
  },
  async runCheck(id: ScenarioId = "bank") {
    await delay(2200);
    return this.getScenario(id);
  },
  async confirmTransaction(ref: string, wasMe: boolean) {
    await delay(250);
    return { ref, was_me: wasMe, simulated: true as const };
  },
  async performAction(
    message_id: string,
    action: Action,
  ): Promise<ActionReceipt> {
    await delay(300);
    const labels: Record<Action, string> = {
      block_sender: "Sender blocked in this demo.",
      report_spam: "Text reported in this demo.",
      call_number_on_card: "Call the number on the back of your card.",
      open_official_app: "Open the official app on your phone.",
      freeze_card: "Use the official app to review card controls.",
      change_password: "Open the official app to change your password.",
      alert_trusted_contact: "Ask someone you trust to sit with you.",
      ignore: "Message dismissed in this demo.",
    };
    return { action, message_id, simulated: true, label: labels[action] };
  },
};
