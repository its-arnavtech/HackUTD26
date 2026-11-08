// L14 System view: what the backend and Nemotron actually do for one message, live.
// Every value here comes from the real run: the trail (`/result`), the privacy log
// (`/privacy`: exact payloads and tool results) and the agent transcript (`/agent`).
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  Check,
  Cpu,
  Gavel,
  MessageSquareText,
  Play,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  ShieldOff,
  Sigma,
  Wrench,
} from "lucide-react";
import { getInbox, getPrivacy, postClicked, resetDemo } from "../api";
import { categoryLabel, verdictLabel } from "../components";
import { useResult } from "../hooks";
import { isRedactionTag, redactedText, splitRedacted } from "../present";
import type { InboxItem, PrivacyView, ResultPoll } from "../types";
import { Shell } from "./Shell";
import { toolTitles } from "./timeline";

// ---------------------------------------------------------------------------
// Agent transcript (GET /api/messages/{id}/agent, local L14 endpoint)
// ---------------------------------------------------------------------------

interface ToolRequest {
  name: string;
  args: Record<string, unknown>;
}
interface Turn {
  n: number;
  ms: number;
  model: string;
  tool_choice: string;
  finish?: string | null;
  sent: string;
  tools_offered: number;
  tool_requests: ToolRequest[];
  requests_as_text: boolean;
  reasoning?: string | null;
  final?: { verdict?: string; confidence_words?: string; reason?: string; plan?: string[]; evidence?: { tool: string }[] } | null;
  reply?: string | null;
}
interface Run {
  mode: string;
  turns: Turn[];
}
interface Transcript {
  message_id: string;
  model: string;
  live: boolean;
  runs: Run[];
}

async function getAgent(id: string): Promise<Transcript | undefined> {
  const res = await fetch(`/api/messages/${encodeURIComponent(id)}/agent`, { credentials: "same-origin" });
  return res.ok ? ((await res.json()) as Transcript) : undefined;
}

interface ToolResult {
  ok: boolean;
  tool: string;
  result?: Record<string, unknown>;
  error?: { message?: string };
}

const SERVICE: Record<string, string> = {
  check_link: "RDAP + lookalike check",
  check_sender: "Official channel list",
  match_campaign: "Campaign fingerprints",
  nessie_recent_activity: "Capital One Nessie API",
  nessie_bill_status: "Capital One Nessie API",
  public_scam_reports: "Google Gemini search",
};

const SCENARIOS: [string, string][] = [
  ["msg_0001", "Scenario 1: bank text"],
  ["msg_0003", "Scenario 3: overdue bill"],
];

function args(a: Record<string, unknown>) {
  const parts = Object.entries(a).map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : JSON.stringify(v)}`);
  return parts.join(", ");
}

function Redacted({ text }: { text: string }) {
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

// ---------------------------------------------------------------------------
// Data for one message: poll + privacy + transcript, refreshed while running
// ---------------------------------------------------------------------------

function useSystem(message?: InboxItem) {
  const id = message?.message_id ?? "";
  const { poll, retry } = useResult(id, Boolean(message));
  const [privacy, setPrivacy] = useState<PrivacyView>();
  const [agent, setAgent] = useState<Transcript>();
  const steps = poll?.trail.length ?? 0;

  useEffect(() => {
    setPrivacy(undefined);
    setAgent(undefined);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let active = true;
    const load = () => {
      getPrivacy(id).then((v) => active && setPrivacy(v)).catch(() => undefined);
      getAgent(id).then((v) => active && v && setAgent(v)).catch(() => undefined);
    };
    load();
    const timer = poll?.status === "done" ? undefined : setInterval(load, 1000);
    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
  }, [id, steps, poll?.status, poll?.mode]);

  return { poll, privacy, agent, retry };
}

// ---------------------------------------------------------------------------
// Pipeline strip
// ---------------------------------------------------------------------------

type StageState = "idle" | "active" | "done";

function Stage({ icon: Icon, name, detail, state }: { icon: typeof Cpu; name: string; detail?: string; state: StageState }) {
  return (
    <div className={`sx-stage sx-${state}`}>
      <span className="sx-stage-icon" aria-hidden="true">
        {state === "done" ? <Check size={16} /> : <Icon size={16} />}
      </span>
      <strong>{name}</strong>
      <span className="sx-stage-detail">{detail ?? (state === "active" ? "running…" : "—")}</span>
    </div>
  );
}

function Pipeline({ message, poll, privacy, agent }: { message?: InboxItem; poll?: ResultPoll; privacy?: PrivacyView; agent?: Transcript }) {
  const run = agent?.runs[agent.runs.length - 1];
  const turns = run?.turns ?? [];
  const tools = (poll?.trail ?? []).filter((t) => t.kind === "tool");
  const done = poll?.status === "done";
  const hidden = privacy ? Object.values(privacy.redaction.counts ?? {}).reduce((a, b) => a + (Number(b) || 0), 0) : 0;
  const cls = privacy?.recipients.find((r) => r.recipient === "nemotron")?.payload?.classifier as { category?: string; score?: number } | undefined;
  const agentMs = turns.reduce((a, t) => a + t.ms, 0);
  const s = (has: boolean, running: boolean): StageState => (has ? "done" : running ? "active" : "idle");
  const started = Boolean(message && poll);
  return (
    <div className="sx-pipeline" aria-label="Pipeline">
      <Stage icon={MessageSquareText} name="Message" state={message ? "done" : "idle"} detail={message ? (message.source === "sms" ? "from a phone" : "received") : undefined} />
      <ArrowRight className="sx-arrow" size={16} aria-hidden="true" />
      <Stage icon={ShieldOff} name="Redact" state={s(Boolean(privacy), started)} detail={privacy ? `${hidden} detail${hidden === 1 ? "" : "s"} hidden` : undefined} />
      <ArrowRight className="sx-arrow" size={16} aria-hidden="true" />
      <Stage icon={Sigma} name="Classifier" state={s(Boolean(cls), started)} detail={cls ? `${categoryLabel(cls.category ?? "")} · ${cls.score?.toFixed(2)}` : undefined} />
      <ArrowRight className="sx-arrow" size={16} aria-hidden="true" />
      <Stage icon={Brain} name="Nemotron agent" state={s(done && turns.length > 0, started)} detail={turns.length ? `${turns.length} model call${turns.length === 1 ? "" : "s"} · ${(agentMs / 1000).toFixed(1)} s` : undefined} />
      <ArrowRight className="sx-arrow" size={16} aria-hidden="true" />
      <Stage icon={Wrench} name="Tools" state={s(done && tools.length > 0, started && turns.length > 0)} detail={tools.length ? `${tools.length} check${tools.length === 1 ? "" : "s"} run` : undefined} />
      <ArrowRight className="sx-arrow" size={16} aria-hidden="true" />
      <Stage icon={ShieldCheck} name="Guardrails" state={s(done, false)} detail={done ? "passed" : undefined} />
      <ArrowRight className="sx-arrow" size={16} aria-hidden="true" />
      <Stage icon={Gavel} name="Verdict" state={s(Boolean(poll?.result), false)} detail={poll?.result ? verdictLabel(poll.result.verdict, poll.result.confidence_words) : undefined} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------

function InputPanel({ message, privacy }: { message?: InboxItem; privacy?: PrivacyView }) {
  const sent = privacy?.recipients.find((r) => r.recipient === "nemotron")?.payload;
  const payload = sent ? Object.fromEntries(Object.entries(sent).filter(([k]) => k !== "tool_results")) : undefined;
  const hidden = privacy ? redactedText(privacy) : undefined;
  return (
    <section className="cx-card sx-panel">
      <h2 className="sx-h">
        <ShieldOff size={16} aria-hidden="true" /> 1 · What goes in
      </h2>
      {!message && <p className="cx-muted">Run a scenario to start.</p>}
      {message && (
        <>
          <span className="cx-eyebrow">Original message</span>
          <p className="cx-mono sx-box">{message.text}</p>
          <span className="cx-eyebrow">What the AI is allowed to see</span>
          <p className="cx-mono sx-box">{hidden ? <Redacted text={hidden} /> : "redacting…"}</p>
          {payload && (
            <details className="sx-details">
              <summary>Exact JSON sent to Nemotron</summary>
              <pre className="sx-pre">{JSON.stringify(payload, null, 2)}</pre>
            </details>
          )}
        </>
      )}
    </section>
  );
}

function AgentPanel({ agent }: { agent?: Transcript }) {
  const runs = agent?.runs ?? [];
  return (
    <section className="cx-card sx-panel">
      <h2 className="sx-h">
        <Brain size={16} aria-hidden="true" /> 2 · Nemotron reasoning, live
      </h2>
      <p className="cx-muted cx-small">
        <Cpu size={13} aria-hidden="true" /> {agent?.model ?? "nvidia/nemotron"} · {agent?.live === false ? "mock data (no model running)" : "real calls to NVIDIA"}
      </p>
      {runs.length === 0 && <p className="cx-muted">Each call to the model appears here as it happens.</p>}
      {runs.map((run, ri) => (
        <div key={ri} className="sx-run">
          {runs.length > 1 && <p className="cx-eyebrow">{run.mode === "recovery" ? "Recovery re-plan" : "First check"}</p>}
          <ol className="sx-turns">
            {run.turns.map((t) => (
              <li key={t.n} className="sx-turn">
                <div className="sx-turn-top">
                  <strong>Call {t.n}</strong>
                  <span className="cx-meta">{(t.ms / 1000).toFixed(2)} s · {t.finish ?? "?"}</span>
                </div>
                <p className="cx-muted cx-small">We sent: {t.sent}{t.n === 1 && t.tools_offered ? ` + ${t.tools_offered} tools it may use` : ""}</p>
                {t.tool_requests.length > 0 && (
                  <div className="sx-asked">
                    <span>Nemotron chose:</span>
                    {t.tool_requests.map((r, i) => (
                      <code key={i} className="sx-call">
                        {r.name}({args(r.args)})
                      </code>
                    ))}
                  </div>
                )}
                {t.reasoning && <blockquote className="sx-reason">“{t.reasoning}”</blockquote>}
                {t.final && (
                  <div className="sx-final">
                    <span className="cx-eyebrow">Final answer (checked by guardrails)</span>
                    <code>
                      {t.final.verdict} · {t.final.confidence_words} · evidence: {(t.final.evidence ?? []).map((e) => e.tool).join(", ") || "none"}
                    </code>
                  </div>
                )}
                {t.reply && !t.final && t.tool_requests.length === 0 && <p className="cx-small cx-muted">Replied: {t.reply}</p>}
              </li>
            ))}
          </ol>
        </div>
      ))}
    </section>
  );
}

function ToolsPanel({ poll, privacy }: { poll?: ResultPoll; privacy?: PrivacyView }) {
  const results = (privacy?.recipients.find((r) => r.recipient === "nemotron")?.payload?.tool_results as ToolResult[] | undefined) ?? [];
  const sentTo = (tool: string) => privacy?.recipients.find((r) => r.recipient === tool);
  const calls = (poll?.trail ?? []).filter((t) => t.kind === "tool");
  const replans = (poll?.trail ?? []).filter((t) => t.kind === "replan");
  return (
    <section className="cx-card sx-panel">
      <h2 className="sx-h">
        <Wrench size={16} aria-hidden="true" /> 3 · Tools it ran
      </h2>
      {calls.length === 0 && <p className="cx-muted">The checks Nemotron picks run here, each against a real source.</p>}
      <ol className="sx-tools">
        {calls.map((call, i) => {
          const tool = call.tool ?? "";
          const raw = results.filter((r) => r.tool === tool)[0];
          const input = sentTo(tool);
          return (
            <li key={`${tool}-${i}`} className={`sx-tool ${raw && !raw.ok ? "sx-tool-failed" : ""}`}>
              <div className="sx-turn-top">
                <strong>{tool ? toolTitles[tool as keyof typeof toolTitles] : "Check"}</strong>
                <span className="cx-chip cx-chip-quiet">{SERVICE[tool] ?? "local"}</span>
                {call.ms != null && <span className="cx-meta">{call.ms} ms</span>}
              </div>
              <p>{call.finding}</p>
              {input && (
                <p className="cx-small cx-muted">
                  Received only: {input.received_fields.join(", ")}
                </p>
              )}
              {raw && (
                <details className="sx-details">
                  <summary>Raw result returned to Nemotron</summary>
                  <pre className="sx-pre">{JSON.stringify(raw.ok ? raw.result : raw.error, null, 2)}</pre>
                </details>
              )}
            </li>
          );
        })}
      </ol>
      {replans.map((r) => (
        <p key={r.step} className="sx-replan">
          <ScanSearch size={14} aria-hidden="true" /> Re-plan: {r.finding}
        </p>
      ))}
    </section>
  );
}

function Outcome({ message, poll, onClicked, busy }: { message?: InboxItem; poll?: ResultPoll; onClicked: () => void; busy: boolean }) {
  const result = poll?.status === "done" ? poll.result : undefined;
  if (!message) return null;
  return (
    <section className={`cx-card sx-outcome ${result ? `cx-verdict-${result.verdict}` : ""}`}>
      <div>
        <span className="cx-eyebrow">4 · What the customer gets</span>
        {result ? (
          <>
            <h2>{verdictLabel(result.verdict, result.confidence_words)}</h2>
            <p>{result.reason}</p>
            {poll?.was_this_you_items[0] && (
              <p className="sx-wty">
                Was this you? ${poll.was_this_you_items[0].amount.toLocaleString("en-US", { minimumFractionDigits: 2 })} {poll.was_this_you_items[0].type} at{" "}
                {poll.was_this_you_items[0].payee}
              </p>
            )}
          </>
        ) : (
          <p className="cx-muted">Waiting for the agent…</p>
        )}
      </div>
      {result && poll?.mode !== "recovery" && result.verdict !== "likely_safe" && (
        <button className="cx-button" onClick={onClicked} disabled={busy}>
          <AlertTriangle size={15} aria-hidden="true" /> She already tapped the link
        </button>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SystemView() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [selected, setSelected] = useState<string>();
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const seen = useRef<Set<string> | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await getInbox());
    } catch {
      /* the header badge shows the API state */
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [load]);

  // A message that arrives from a phone opens on its own.
  useEffect(() => {
    if (items.length === 0) return;
    if (seen.current === null) {
      seen.current = new Set(items.map((i) => i.message_id));
      return;
    }
    const fresh = items.find((i) => i.source === "sms" && !seen.current!.has(i.message_id));
    items.forEach((i) => seen.current!.add(i.message_id));
    if (fresh) {
      setSelected(fresh.message_id);
      setVersion((v) => v + 1);
    }
  }, [items]);

  const message = items.find((i) => i.message_id === selected);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell wide>
      <div className="cx-scenarios" role="toolbar" aria-label="Demo scenarios">
        {SCENARIOS.map(([id, label]) => (
          <button
            key={id}
            className={`cx-button ${id === "msg_0001" ? "cx-button-primary" : ""}`}
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await resetDemo().catch(() => undefined);
                await load();
                setSelected(id);
                setVersion((v) => v + 1);
              })
            }
          >
            <Play size={15} aria-hidden="true" /> {label}
          </button>
        ))}
        <button
          className="cx-button cx-button-ghost"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await resetDemo().catch(() => undefined);
              setSelected(undefined);
              await load();
            })
          }
        >
          <RotateCcw size={15} aria-hidden="true" /> Reset
        </button>
        <span className="cx-hint">Everything below is the live system: real Nemotron calls, real tool results.</span>
      </div>
      <SystemBody
        key={`${selected ?? "none"}-${version}`}
        message={message}
        busy={busy}
        onClicked={() =>
          void run(async () => {
            if (!selected) return;
            await postClicked(selected);
            setVersion((v) => v + 1);
          })
        }
      />
    </Shell>
  );
}

function SystemBody({ message, onClicked, busy }: { message?: InboxItem; onClicked: () => void; busy: boolean }) {
  const { poll, privacy, agent } = useSystem(message);
  return (
    <>
      <Pipeline message={message} poll={poll} privacy={privacy} agent={agent} />
      <div className="sx-grid">
        <InputPanel message={message} privacy={privacy} />
        <AgentPanel agent={agent} />
        <ToolsPanel poll={poll} privacy={privacy} />
      </div>
      <Outcome message={message} poll={poll} onClicked={onClicked} busy={busy} />
    </>
  );
}
