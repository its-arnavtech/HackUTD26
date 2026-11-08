// L15 features in the console's existing look (Shell + .cx classes; no new visual design):
// agent accuracy, the agent's bank-activity source, trusted-contact alert, scam-wave early warning.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, BarChart3, Database, Radio, Send, UserRound, Waves } from "lucide-react";
import { categoryLabel } from "../components";
import type { InboxItem, ResultPoll } from "../types";
import { Shell } from "./Shell";
import { TrustedAlertConsole } from "../trustedAlert";
import { toolTitles } from "./timeline";

// ---------------------------------------------------------------------------
// tiny fetch helpers (same-origin cookies + CSRF header, like api.ts)
// ---------------------------------------------------------------------------

function csrf(): Record<string, string> {
  const m = typeof document !== "undefined" ? document.cookie.match(/(?:^|;\s*)sa_csrf=([^;]+)/) : null;
  return m ? { "X-CSRF-Token": decodeURIComponent(m[1]) } : {};
}

export async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(method === "GET" ? {} : csrf()) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error((data as { detail?: string }).detail || `HTTP ${res.status}`), { status: res.status });
  return data as T;
}

const pct = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);

// ---------------------------------------------------------------------------
// 1. Agent accuracy
// ---------------------------------------------------------------------------

interface AgentMetrics {
  generated_at: string;
  model: string;
  dataset: string;
  n: number;
  errors: number;
  per_category: number;
  accuracy: number | null;
  unsure: number | null;
  scams_caught: number | null;
  false_alarms: number | null;
  avg_seconds: number | null;
  worst_seconds: number | null;
  avg_tool_calls: number | null;
  tool_use: Record<string, number>;
  categories: { category: string; n: number; correct: number | null; unsure: number | null; wrong: number | null }[];
}

export function AgentAccuracyPage() {
  const [m, setM] = useState<AgentMetrics>();
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    call<AgentMetrics>("/api/agent-metrics")
      .then(setM)
      .catch(() => setMissing(true));
  }, []);
  return (
    <Shell>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Agent accuracy</p>
        <h1>How often the Nemotron agent itself is right</h1>
        <p className="cx-muted">
          The full pipeline (our classifier, then the live Nemotron agent with its tools) on held-out test messages it was
          never tuned on, balanced across all nine categories. &ldquo;Not sure&rdquo; is counted on its own, never as right.
        </p>
      </div>
      {missing && (
        <p className="cx-alert">
          Not measured yet. Run <code>python -m scripts.evaluate_agent --per-category 5</code> from <code>backend/</code>.
        </p>
      )}
      {m && (
        <>
          <div className="cx-grid">
            {[
              ["Right", pct(m.accuracy), `${m.n} held-out messages`],
              ["Scams caught", pct(m.scams_caught), "verdict “likely scam” on a scam"],
              ["False alarms", pct(m.false_alarms), "real messages called a scam"],
              ["Not sure", pct(m.unsure), "honest uncertainty, shown to the customer"],
              ["Time per check", m.avg_seconds == null ? "—" : `${m.avg_seconds}s`, `worst ${m.worst_seconds}s · ${m.avg_tool_calls} tools on average`],
            ].map(([label, value, note]) => (
              <article key={label} className="cx-card">
                <span className="cx-eyebrow">{label}</span>
                <p className="cx-big-number">{value}</p>
                <p className="cx-muted cx-small">{note}</p>
              </article>
            ))}
          </div>
          <section className="cx-card cx-audit">
            <div className="cx-row-top">
              <BarChart3 size={16} aria-hidden="true" />
              <strong>By category</strong>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Messages</th>
                  <th>Right</th>
                  <th>Not sure</th>
                  <th>Wrong</th>
                </tr>
              </thead>
              <tbody>
                {m.categories.map((r) => (
                  <tr key={r.category}>
                    <td>{categoryLabel(r.category)}</td>
                    <td>{r.n}</td>
                    <td>{pct(r.correct)}</td>
                    <td>{pct(r.unsure)}</td>
                    <td>{pct(r.wrong)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="cx-card cx-audit">
            <div className="cx-row-top">
              <strong>Which checks the agent chose</strong>
              <span className="cx-muted cx-small">share of messages where each tool ran</span>
            </div>
            <table>
              <tbody>
                {Object.entries(m.tool_use).map(([tool, share]) => (
                  <tr key={tool}>
                    <td>{toolTitles[tool as keyof typeof toolTitles] ?? tool}</td>
                    <td>{pct(share)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="cx-muted cx-small">
              {m.model} · {m.dataset} · measured {new Date(m.generated_at).toLocaleString()}
              {m.errors ? ` · ${m.errors} could not be scored` : ""}
            </p>
          </section>
        </>
      )}
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// 2. The agent's bank-activity source
// ---------------------------------------------------------------------------

export interface ActiveSource {
  source: string;
  label: string;
  live_nessie: boolean;
  records: number;
  payment_sources?: string[];
}

export function useActiveSource() {
  const [active, setActive] = useState<ActiveSource>();
  const refresh = useCallback(() => {
    call<ActiveSource>("/api/connect/active")
      .then(setActive)
      .catch(() => undefined);
  }, []);
  useEffect(refresh, [refresh]);
  return { active, refresh };
}

/** One line under "Tools it ran": which system answered the bank-activity check. */
export function ActiveSourceNote() {
  const { active } = useActiveSource();
  if (!active) return null;
  return (
    <p className="cx-muted cx-small">
      <Database size={13} aria-hidden="true" /> Bank activity source: <strong>{active.label}</strong>
      {active.live_nessie ? " (live)" : ` · ${active.records} records via its mapping file`} ·{" "}
      <Link to="/connect">change</Link>
    </p>
  );
}

// ---------------------------------------------------------------------------
// 3. Trusted-contact alert
// ---------------------------------------------------------------------------

interface ContactView {
  contact: { name: string; phone_masked: string } | null;
}

/** Under the customer outcome: tell a trusted person, on the customer's tap only. */
export function TrustedContactCard({ message, poll }: { message?: InboxItem; poll?: ResultPoll }) {
  const [contact, setContact] = useState<ContactView["contact"]>();
  const [loaded, setLoaded] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [problem, setProblem] = useState<string>();
  const result = poll?.status === "done" ? poll.result : undefined;

  useEffect(() => {
    call<ContactView>("/api/trusted-contact")
      .then((v) => setContact(v.contact))
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, []);

  if (!message || !result || result.verdict === "likely_safe" || !loaded) return null;

  const save = async () => {
    setProblem(undefined);
    try {
      setContact((await call<ContactView>("/api/trusted-contact", "PUT", { name, phone })).contact);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That didn’t save.");
    }
  };

  return (
    <section className="cx-card sx-trusted" aria-label="Trusted contact">
      <div className="cx-row-top">
        <UserRound size={16} aria-hidden="true" />
        <strong>Trusted contact</strong>
        <span className="cx-muted cx-small">Someone who can call right away. Only on her tap, and never with the message itself.</span>
      </div>
      {contact ? (
        <div className="sx-trusted-row">
          <p>
            {contact.name} <span className="cx-muted">({contact.phone_masked})</span>
          </p>
          <TrustedAlertConsole messageId={message.message_id} label={`Tell ${contact.name}`} />
        </div>
      ) : (
        <div className="sx-trusted-form">
          <input className="sx-input" placeholder="Name, e.g. Maya" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} aria-label="Trusted contact name" />
          <input className="sx-input" placeholder="Phone, e.g. +1 512 555 4471" value={phone} maxLength={24} onChange={(e) => setPhone(e.target.value)} aria-label="Trusted contact phone" />
          <button className="cx-button" disabled={!name.trim() || !phone.trim()} onClick={() => void save()}>
            Save contact
          </button>
        </div>
      )}
      {problem && <p className="cx-alert">{problem}</p>}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 4. Scam-wave early warning
// ---------------------------------------------------------------------------

interface Wave {
  id: string;
  brand: string | null;
  category: string | null;
  count_last_hour: number;
  count_previous_hour: number;
  trend: string;
  first_seen: string;
  example: string;
  warned: boolean;
}

export function useWaves(intervalMs = 5000) {
  const [waves, setWaves] = useState<Wave[]>([]);
  const refresh = useCallback(() => {
    call<{ waves: Wave[] }>("/api/waves")
      .then((d) => setWaves(d.waves))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, intervalMs);
    return () => clearInterval(t);
  }, [refresh, intervalMs]);
  return { waves, refresh };
}

/** A one-line notice on the System view while a wave is active. */
export function WaveNotice() {
  const { waves } = useWaves();
  if (waves.length === 0) return null;
  const w = waves[0];
  return (
    <p className="cx-alert sx-wave-notice" role="status">
      <AlertTriangle size={14} aria-hidden="true" /> Scam wave: {w.count_last_hour} fake {w.brand ?? ""}{" "}
      {categoryLabel(w.category ?? "").toLowerCase()} texts in the last hour. <Link to="/waves">See waves</Link>
    </p>
  );
}

export function WavesPage() {
  const { waves, refresh } = useWaves(3000);
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<Record<string, string>>({});

  const simulate = async () => {
    setBusy(true);
    try {
      await call("/api/waves/simulate", "POST", {});
      refresh();
    } finally {
      setBusy(false);
    }
  };
  const warn = async (id: string) => {
    const r = await call<{ text: string }>(`/api/waves/${encodeURIComponent(id)}/warn`, "POST");
    setWarnings((w) => ({ ...w, [id]: r.text }));
    refresh();
  };

  return (
    <Shell>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Scam waves</p>
        <h1>Catch the wave before it reaches customers</h1>
        <p className="cx-muted">
          Scams arrive in bursts: one brand, one lure, many wordings and look-alike links. Every message SentinelAI checks
          adds to a fingerprint count (never the text). Five or more of one brand and scam type in an hour, or three times
          the hour before, is a wave.
        </p>
      </div>
      <div className="cx-scenarios">
        <button className="cx-button cx-button-primary" disabled={busy} onClick={() => void simulate()}>
          <Radio size={15} aria-hidden="true" /> Simulate a wave
        </button>
        <span className="cx-hint">Replays one seeded campaign through the fingerprinting only: no model calls.</span>
      </div>
      {waves.length === 0 && <p className="cx-muted">No active waves right now.</p>}
      <div className="cx-grid">
        {waves.map((w) => (
          <article key={w.id} className="cx-card">
            <div className="cx-row-top">
              <Waves size={16} aria-hidden="true" />
              <strong>
                Fake {w.brand ?? "unbranded"} · {categoryLabel(w.category ?? "")}
              </strong>
              <span className="cx-chip">{w.trend}</span>
            </div>
            <p className="cx-big-number">
              {w.count_last_hour}
              <span className="cx-muted"> in the last hour</span>
            </p>
            <p className="cx-muted cx-small">
              {w.count_previous_hour} the hour before · first seen {new Date(w.first_seen).toLocaleTimeString()}
            </p>
            <p className="cx-mono cx-example">{w.example}</p>
            {warnings[w.id] ? (
              <p className="cx-receipt" role="status">
                <Send size={14} aria-hidden="true" /> Simulated broadcast: &ldquo;{warnings[w.id]}&rdquo;
              </p>
            ) : (
              <button className="cx-button" onClick={() => void warn(w.id)} disabled={w.warned}>
                <Send size={15} aria-hidden="true" /> {w.warned ? "Customers warned" : "Warn customers"}
              </button>
            )}
          </article>
        ))}
      </div>
    </Shell>
  );
}
