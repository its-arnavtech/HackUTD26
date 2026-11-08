// L14 "Plug into any system": records from six different payment or carrier systems,
// each in its own native format, mapped live into one canonical event by a YAML file,
// and the fraud signals the agent sees from those events.
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Database, FileCode2, Play, ShieldCheck } from "lucide-react";
import { Shell } from "./Shell";
import { call, useActiveSource } from "./features";

interface FieldMap {
  canonical: string;
  from: string[];
  transform: string;
  notes?: string;
}
interface Source {
  name: string;
  label: string;
  description: string;
  fields: FieldMap[];
  sample: Record<string, unknown>[];
}
interface Preview {
  source: string;
  label: string;
  message_at: string;
  canonical: Record<string, unknown>[];
  signals: { signal: string; detail: string }[];
}

const SIGNAL_LABEL: Record<string, string> = {
  new_payee: "New payee",
  amount_far_above_usual: "Amount far above usual",
  new_channel: "New payment channel",
  soon_after_text: "Right after the scam text",
  account_takeover_step: "Account takeover step",
  takeover_before_payment: "Takeover before payment",
};

function compact(event: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(event)) {
    if (v === null || v === undefined) continue;
    if (typeof v === "object" && !Array.isArray(v)) {
      const inner = compact(v as Record<string, unknown>);
      if (Object.keys(inner).length) out[k] = inner;
    } else out[k] = v;
  }
  return out;
}

export default function Connect() {
  const [sources, setSources] = useState<Source[]>([]);
  const [current, setCurrent] = useState<string>("nessie");
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    fetch("/api/connect/sources", { credentials: "same-origin" })
      .then((r) => (r.ok ? (r.json() as Promise<Source[]>) : []))
      .then(setSources)
      .catch(() => setProblem("Could not load the source systems."));
  }, []);

  const source = sources.find((s) => s.name === current);
  const { active, refresh: refreshActive } = useActiveSource();
  const usable = active?.payment_sources?.includes(current) ?? false;
  const useForAgent = async () => {
    setProblem(undefined);
    let records: unknown;
    try {
      records = JSON.parse(text);
    } catch {
      setProblem("The records are not valid JSON.");
      return;
    }
    try {
      await call("/api/connect/active", "POST", { source: current, records });
      refreshActive();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not switch the agent's source.");
    }
  };
  const backToNessie = async () => {
    await call("/api/connect/active", "DELETE");
    refreshActive();
  };

  const run = async (name: string, records?: unknown) => {
    setProblem(undefined);
    try {
      const res = await fetch(`/api/connect/${encodeURIComponent(name)}/preview`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(records === undefined ? {} : { records }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setPreview(await res.json());
    } catch {
      setProblem("That did not map. Check the records are a JSON list of objects.");
    }
  };

  useEffect(() => {
    if (!source) return;
    setText(JSON.stringify(source.sample, null, 2));
    void run(source.name);
  }, [source?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const runEdited = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setProblem("The records are not valid JSON.");
      return;
    }
    if (!Array.isArray(parsed)) {
      setProblem("The records must be a JSON list.");
      return;
    }
    void run(current, parsed);
  };

  return (
    <Shell wide>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Plug into any system</p>
        <h1>One fraud brain, any bank or carrier</h1>
        <p className="cx-muted">
          Every institution stores account activity differently. SentinelAI reads it through a small mapping file per
          system, turns it into one canonical event, and looks for the same fraud signals. Adding a new system is a new
          file, not new code. Pick a system, edit its records, and watch the mapping run.
        </p>
      </div>

      <div className="cn-sources" role="tablist" aria-label="Source systems">
        {sources.map((s) => (
          <button key={s.name} role="tab" aria-selected={s.name === current} className={`cx-button cn-source ${s.name === current ? "active" : ""}`} onClick={() => setCurrent(s.name)}>
            <Database size={14} aria-hidden="true" /> {s.label}
          </button>
        ))}
      </div>
      {active && (
        <div className="cx-scenarios">
          <span className="cx-hint cn-active">
            <Database size={14} aria-hidden="true" /> The agent&apos;s bank-activity check reads: <strong>{active.label}</strong>
          </span>
          {usable && active.source !== current && (
            <button className="cx-button cx-button-primary" onClick={() => void useForAgent()}>
              Use this system for the agent
            </button>
          )}
          {!active.live_nessie && (
            <button className="cx-button cx-button-ghost" onClick={() => void backToNessie()}>
              Back to Nessie
            </button>
          )}
          {!usable && <span className="cx-muted cx-small">Carrier events are preview-only: the agent needs a carrier-events tool for them.</span>}
        </div>
      )}
      {problem && <p className="cx-alert">{problem}</p>}

      {source && (
        <div className="cn-grid">
          <section className="cx-card sx-panel">
            <h2 className="sx-h">
              <Database size={16} aria-hidden="true" /> 1 · Records in {source.label}&apos;s own format
            </h2>
            <p className="cx-muted cx-small">{source.description}</p>
            <textarea className="sx-input cn-editor" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="Source records (JSON)" />
            <button className="cx-button cx-button-primary" onClick={runEdited}>
              <Play size={15} aria-hidden="true" /> Map these records
            </button>
          </section>

          <section className="cx-card sx-panel">
            <h2 className="sx-h">
              <FileCode2 size={16} aria-hidden="true" /> 2 · The mapping file ({source.name}.yaml)
            </h2>
            <table className="cn-map">
              <thead>
                <tr>
                  <th>Their field</th>
                  <th />
                  <th>Our canonical field</th>
                  <th>How</th>
                </tr>
              </thead>
              <tbody>
                {source.fields.map((f) => (
                  <tr key={f.canonical}>
                    <td>
                      <code>{f.from.join(" | ")}</code>
                    </td>
                    <td>
                      <ArrowRight size={12} aria-hidden="true" />
                    </td>
                    <td>
                      <code>{f.canonical}</code>
                    </td>
                    <td className="cx-muted">{f.transform.replace(/_/g, " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="cx-card sx-panel">
            <h2 className="sx-h">
              <ShieldCheck size={16} aria-hidden="true" /> 3 · What the agent sees
            </h2>
            <span className="cx-eyebrow">Fraud signals (same rules for every system)</span>
            {preview && preview.signals.length === 0 && <p className="cn-none">No warning signs in this activity.</p>}
            {preview?.signals.map((s, i) => (
              <div key={i} className="cn-signal">
                <strong>
                  <AlertTriangle size={13} aria-hidden="true" /> {SIGNAL_LABEL[s.signal] ?? s.signal}
                </strong>
                <span>{s.detail}</span>
              </div>
            ))}
            {preview && (
              <details className="sx-details" open>
                <summary>Canonical events ({preview.canonical.length})</summary>
                <pre className="sx-pre">{JSON.stringify(preview.canonical.map(compact), null, 2)}</pre>
              </details>
            )}
            <p className="cx-muted cx-small">The scam text arrived at {preview ? new Date(preview.message_at).toLocaleString() : "…"}.</p>
          </section>
        </div>
      )}
    </Shell>
  );
}
