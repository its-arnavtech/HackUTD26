import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { api } from "./api";
import { ResultCard } from "./components";
import type { Action, ScenarioId, ResultState } from "./types";
const store = new Map<string, string>();
vi.stubGlobal("sessionStorage", {
  getItem: (key: string) => store.get(key) || null,
  setItem: (key: string, value: string) => store.set(key, value),
});
afterEach(() => {
  store.clear();
  vi.useRealTimers();
});
const allowed: Action[] = [
  "block_sender",
  "report_spam",
  "call_number_on_card",
  "open_official_app",
  "freeze_card",
  "change_password",
  "alert_trusted_contact",
  "ignore",
];
describe("the prototype’s safety and data boundaries", () => {
  it.each<ScenarioId>(["bank", "recovery", "billing"])(
    "%s follows the agent result contract",
    async (id) => {
      const { result, trail } = await api.getScenario(id);
      expect(result.actions.length).toBeLessThanOrEqual(3);
      expect(result.actions.every((action) => allowed.includes(action))).toBe(
        true,
      );
      expect(
        new Set(result.evidence.map((e) => e.tool)).size,
      ).toBeGreaterThanOrEqual(2);
      expect(trail.every((e) => e.step > 0 && Number.isFinite(e.ms))).toBe(
        true,
      );
      expect(result.reason).not.toMatch(
        /https?:|www\.|\d{3}[-. ]\d{3}[-. ]\d{4}|%|your account is fine/i,
      );
    },
  );
  it("preserves the different bank and bill plans and the recovery reference", async () => {
    const bank = await api.getScenario("bank");
    const billing = await api.getScenario("billing");
    const recovery = await api.getScenario("recovery");
    expect(bank.result.plan).toContain("nessie_recent_activity");
    expect(billing.result.plan).not.toContain("nessie_recent_activity");
    expect(billing.result.plan).toContain("nessie_bill_status");
    expect(recovery.result.replan).toBe(true);
    expect(recovery.result.was_this_you).toEqual(["txn_3"]);
    expect((await api.getRecovery()).transaction.ref).toBe("txn_3");
  });
  it.each<ResultState>(["scam", "unsure", "safe", "mixed"])(
    "renders %s with words, no percentage, and at most two card buttons",
    async (state) => {
      const data = await api.getScenario("bank", state);
      const html = renderToStaticMarkup(
        <ResultCard
          result={data.result}
          activity={data.activity_summary}
          nextStep={data.next_step}
          onPrimary={() => {}}
          onTrail={() => {}}
        />,
      );
      expect(html).not.toContain("%");
      expect((html.match(/<button/g) || []).length).toBe(2);
      expect(html).toContain("<svg");
      expect(data.trail.at(-1)?.kind).toBe("verdict");
      if (state !== "scam")
        expect(data.trail.at(-1)?.finding).not.toBe("Very likely a scam.");
    },
  );
  it("does not claim bank activity was checked after consent was skipped", async () => {
    store.set("sentinel-linked", "false");
    const value = await api.getScenario("bank");
    expect(value.result.plan).not.toContain("nessie_recent_activity");
    expect(value.activity_summary).toContain("wasn’t checked");
    expect(value.result.evidence).toHaveLength(2);
    const bill = await api.getScenario("billing");
    expect(bill.result.plan).not.toContain("nessie_bill_status");
    expect(bill.activity_summary).toContain("wasn’t checked");
    expect((await api.getRecovery()).linked).toBe(false);
  });
  it("keeps privacy payloads redacted and public lookup generic", async () => {
    const value = await api.getPrivacy();
    expect(value.text_redacted).toBe((await api.getScenario()).message.text);
    expect(value.text_redacted).toContain("<PERSON>");
    expect(value.text_redacted).toContain("<ACCOUNT_DIGITS>");
    const publicLookup = value.recipients.find((x) =>
      x.name.includes("Gemini"),
    )!;
    expect(publicLookup.received.join(" ")).not.toMatch(/Linda|900|txn_3/);
  });
  it("returns independent fixtures so a UI update cannot mutate shared data", async () => {
    const first = await api.getScenario();
    first.result.actions.length = 0;
    expect((await api.getScenario()).result.actions.length).toBeGreaterThan(0);
  });
  it("returns only a simulated receipt after an explicit action call", async () => {
    vi.useFakeTimers();
    const pending = api.performAction("msg_0142", "block_sender");
    await vi.advanceTimersByTimeAsync(300);
    expect(await pending).toMatchObject({
      action: "block_sender",
      message_id: "msg_0142",
      simulated: true,
    });
  });
  it("marks judge metrics as illustrative on every dataset", async () => {
    for (const dataset of ["public", "synthetic"] as const) {
      const value = await api.getMetrics(dataset);
      expect(value.illustrative).toBe(true);
      expect(value.dataset).toContain("illustrative");
      expect(value.sample_size).toBe(
        value.rows.reduce((sum, row) => sum + row.support, 0),
      );
    }
  });
});
