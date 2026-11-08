// L15b: Privacy Control Center, "Before you act" scam interruption, and opt-in personal scam memory.
// Same console frame and .cx tokens as the rest (no new visual design).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Ban, Brain, Check, Eye, EyeOff, Hand, KeyRound, ShieldCheck, Trash2 } from "lucide-react";
import type { InboxItem, PrivacyView, ResultPoll } from "../types";
import { call } from "./features";
import { Shell } from "./Shell";

// ---------------------------------------------------------------------------
// Scam interruption: pause before you act
// ---------------------------------------------------------------------------

interface Contact {
  brand: string | null;
  verified: boolean;
  advice: string;
  domains: string[];
  short_codes: string[];
}

const ASK: Record<string, string> = {
  login: "sign in on their page",
  payment: "pay or send money",
  card_details: "enter card details",
  otp: "share a one-time code",
  personal_info: "share personal details",
};

export function InterruptionCard({ poll, privacy }: { poll?: ResultPoll; privacy?: PrivacyView }) {
  const [contact, setContact] = useState<Contact>();
  const payload = privacy?.recipients.find((r) => r.recipient === "nemotron")?.payload as
    | { sender?: { claimed_brand?: string | null }; features?: { asks_for?: string[]; urgency_deadline?: string | null } }
    | undefined;
  const brand = payload?.sender?.claimed_brand ?? null;
  const result = poll?.status === "done" ? poll.result : undefined;

  useEffect(() => {
    if (!result || result.verdict === "likely_safe") return;
    call<Contact>(`/api/official-contact${brand ? `?brand=${encodeURIComponent(brand)}` : ""}`)
      .then(setContact)
      .catch(() => undefined);
  }, [brand, result?.verdict]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!result || result.verdict === "likely_safe" || poll?.mode === "recovery") return null;
  const asks = (payload?.features?.asks_for ?? []).map((a) => ASK[a] ?? a.replace(/_/g, " "));
  return (
    <section className="cx-card sx-interrupt" aria-label="Before you act">
      <div className="cx-row-top">
        <Hand size={16} aria-hidden="true" />
        <strong>Before you tap the link or send money, let&apos;s check this request</strong>
      </div>
      <div className="sx-interrupt-grid">
        <div>
          <span className="cx-eyebrow">Why it&apos;s suspicious</span>
          <p>{result.reason}</p>
          {payload?.features?.urgency_deadline && (
            <p className="cx-muted cx-small">It pushes a deadline ({payload.features.urgency_deadline}), a classic pressure tactic.</p>
          )}
        </div>
        <div>
          <span className="cx-eyebrow">Reach {contact?.brand ?? brand ?? "the company"} yourself</span>
          <p>{contact?.advice ?? "Use the company's official app or website, typed in yourself."}</p>
          {contact?.verified && contact.domains.length > 0 && (
            <p className="cx-small">
              Official website: <strong>{contact.domains.join(", ")}</strong>
              {contact.short_codes.length > 0 && <> · texts only from {contact.short_codes.slice(0, 3).join(", ")}</>}
              <span className="cx-muted"> (verified from their own pages, not from this message)</span>
            </p>
          )}
        </div>
        <div>
          <span className="cx-eyebrow">Don&apos;t</span>
          <ul className="sx-list">
            <li>
              <Ban size={13} aria-hidden="true" /> tap the link or reply
            </li>
            {asks.map((a) => (
              <li key={a}>
                <Ban size={13} aria-hidden="true" /> {a} because the message asks
              </li>
            ))}
            <li>
              <Ban size={13} aria-hidden="true" /> call a number from the message
            </li>
          </ul>
        </div>
        <div>
          <span className="cx-eyebrow">Already sent money or details?</span>
          <p>Call your bank on the number on your card now: transfers are easiest to stop in the first hour. Then use &ldquo;She already tapped the link&rdquo; above for a recovery check.</p>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Personal scam memory (opt-in)
// ---------------------------------------------------------------------------

interface MemoryView {
  consent: boolean;
  items: { at: string; brand: string | null; category: string | null; domain: string | null }[];
}
interface MemoryResult {
  consent: boolean;
  matches: { at: string; brand: string | null; why: string }[];
  pending?: boolean;
}

export function MemoryCard({ message, poll }: { message?: InboxItem; poll?: ResultPoll }) {
  const [consent, setConsent] = useState<boolean>();
  const [result, setResult] = useState<MemoryResult>();
  const done = poll?.status === "done";

  useEffect(() => {
    call<MemoryView>("/api/memory")
      .then((v) => setConsent(v.consent))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!message || !done || !consent) return;
    call<MemoryResult>(`/api/memory/${encodeURIComponent(message.message_id)}`, "POST")
      .then(setResult)
      .catch(() => undefined);
  }, [message?.message_id, done, consent]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!message || !done || consent === undefined) return null;
  const toggle = async () => setConsent((await call<MemoryView>("/api/memory/consent", "PUT", { on: !consent })).consent);

  return (
    <section className="cx-card sx-trusted" aria-label="Personal scam memory">
      <div className="cx-row-top">
        <Brain size={16} aria-hidden="true" />
        <strong>Personal scam memory</strong>
        <span className="cx-muted cx-small">Optional. Keeps only the brand, scam type, link domain and a wording fingerprint, never the message.</span>
      </div>
      {!consent ? (
        <div className="sx-trusted-row">
          <p className="cx-muted">Off. Turn it on to spot the same scam coming back from a different number.</p>
          <button className="cx-button" onClick={() => void toggle()}>
            Turn on
          </button>
        </div>
      ) : (
        <>
          {result?.matches.length ? (
            result.matches.map((m, i) => (
              <p key={i} className="cn-signal">
                <strong>Seen before</strong>
                <span>
                  This uses {m.why} as a message you checked {new Date(m.at).toLocaleString()}.
                </span>
              </p>
            ))
          ) : (
            <p className="cx-muted">Nothing matches earlier messages. This one&apos;s indicators are now remembered.</p>
          )}
          <button className="cx-link-button" onClick={() => void toggle()}>
            Turn off and delete
          </button>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Privacy Control Center
// ---------------------------------------------------------------------------

const ROWS: [typeof Eye, string, string][] = [
  [EyeOff, "Original message", "Redacted on our server before any AI or tool sees it; kept in memory only, never on disk"],
  [EyeOff, "Names, phone numbers, account digits, links", "Replaced with tags like <PERSON> and <URL_1> before analysis"],
  [KeyRound, "SSN, passwords, one-time codes", "Never requested"],
  [Ban, "Your contacts", "Not accessed"],
  [Eye, "What each model and tool received", "Logged per message and shown to you in the privacy panel"],
  [Brain, "Scam memory", "Off unless you turn it on; brand, scam type, link domain and a wording hash only"],
  [ShieldCheck, "Scam-wave counts", "Anonymous: a fingerprint and a count, no text and no identity"],
  [Ban, "Training on your messages", "Never"],
];

export function PrivacyCenterPage() {
  const [memory, setMemory] = useState<MemoryView>();
  const [contact, setContact] = useState<{ name: string; phone_masked: string } | null>();
  const [deleted, setDeleted] = useState<string>();

  const load = () => {
    call<MemoryView>("/api/memory").then(setMemory).catch(() => undefined);
    call<{ contact: { name: string; phone_masked: string } | null }>("/api/trusted-contact")
      .then((v) => setContact(v.contact))
      .catch(() => undefined);
  };
  useEffect(load, []);

  const deleteAll = async () => {
    const r = await call<{ messages_removed: number }>("/api/my-data", "DELETE");
    setDeleted(`Deleted: ${r.messages_removed} message${r.messages_removed === 1 ? "" : "s"}, your scam memory and your trusted contact.`);
    load();
  };

  return (
    <Shell>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Privacy Control Center</p>
        <h1>Exactly what SentinelAI handles, and what it never touches</h1>
        <p className="cx-muted">This is how the system actually behaves, not a promise. You can delete what&apos;s kept at any time.</p>
      </div>
      <section className="cx-card cx-audit">
        <table>
          <thead>
            <tr>
              <th>Information</th>
              <th>What happens to it</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([Icon, what, status]) => (
              <tr key={what}>
                <td>
                  <Icon size={14} aria-hidden="true" /> {what}
                </td>
                <td>{status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="cx-card cx-audit">
        <div className="cx-row-top">
          <strong>Kept for you right now</strong>
        </div>
        <ul className="sx-list">
          <li>
            <Check size={13} aria-hidden="true" /> Scam memory: {memory?.consent ? `on, ${memory.items.length} indicator set(s)` : "off"}
          </li>
          <li>
            <Check size={13} aria-hidden="true" /> Trusted contact: {contact ? `${contact.name} (${contact.phone_masked})` : "none"}
          </li>
          <li>
            <Check size={13} aria-hidden="true" /> Checked messages: in memory on this server only, never written to disk
          </li>
        </ul>
        <button className="cx-button" onClick={() => void deleteAll()}>
          <Trash2 size={15} aria-hidden="true" /> Delete my data
        </button>
        {deleted && (
          <p className="cx-receipt" role="status">
            <Check size={14} aria-hidden="true" /> {deleted}
          </p>
        )}
        <p className="cx-muted cx-small">
          More detail per message in the <Link to="/system">System view</Link> (&ldquo;What goes in&rdquo;) and on the{" "}
          <Link to="/security">Security</Link> page.
        </p>
      </section>
    </Shell>
  );
}
