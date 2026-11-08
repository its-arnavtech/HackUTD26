import { useEffect, useState } from "react";
import {
  ClipboardList,
  EyeOff,
  Fingerprint,
  KeyRound,
  Lock,
  ScrollText,
  ShieldCheck,
  UserCog,
  Users,
  VenetianMask,
} from "lucide-react";
import { getCampaigns, getMe } from "../api";
import { categoryLabel } from "../components";
import { useData, useHealth } from "../hooks";
import { isRedactionTag, splitRedacted } from "../present";
import AccuracyPage from "../screens/AccuracyPage";
import type { AuditView, Me } from "../types";
import { Shell } from "./Shell";

const day = (value: string) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "America/Chicago" }).format(new Date(value));

/** `/patterns`: scam campaigns grouped from anonymized fingerprints. */
export function PatternsPage() {
  const { data, failure } = useData(() => getCampaigns(), []);
  return (
    <Shell>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Scam patterns</p>
        <h1>Messages that belong to the same scam</h1>
        <p className="cx-muted">
          Grouped by an anonymized fingerprint: wording template, link pattern and claimed sender. No message text is
          stored, only the pattern.
        </p>
      </div>
      {failure && <p className="cx-alert">Couldn’t load the patterns.</p>}
      <div className="cx-grid">
        {(data ?? []).map((campaign) => (
          <article key={campaign.campaign_id} className="cx-card">
            <div className="cx-row-top">
              <Users size={16} aria-hidden="true" />
              <strong>{categoryLabel(campaign.category)}</strong>
              {campaign.claimed_brand && <span className="cx-chip">claims to be {campaign.claimed_brand}</span>}
            </div>
            <p className="cx-big-number">
              {campaign.count_total}
              <span className="cx-muted"> similar texts on record</span>
            </p>
            <p className="cx-muted">
              {campaign.count_last_24h} in the last 24 hours · first seen {day(campaign.first_seen)}
              {campaign.domain_pattern ? ` · links like ${campaign.domain_pattern}` : ""}
            </p>
            <p className="cx-mono cx-example">
              {splitRedacted(campaign.redacted_example).map((part, i) =>
                isRedactionTag(part) ? (
                  <mark key={i} className="cx-tag">
                    {part}
                  </mark>
                ) : (
                  <span key={i}>{part}</span>
                ),
              )}
            </p>
          </article>
        ))}
      </div>
    </Shell>
  );
}

/** `/accuracy`: the existing accuracy screen inside the new frame. */
export function AccuracyShell() {
  return (
    <Shell>
      <div className="cx-legacy">
        <AccuracyPage />
      </div>
    </Shell>
  );
}

const pillars: { icon: typeof Lock; name: string; how: string }[] = [
  { icon: Fingerprint, name: "Authentication", how: "Passkeys first (phishing-resistant: the browser only signs for our site). Password with Argon2id plus a 6-digit authenticator code as the fallback. Invite-only accounts, lockout after 5 tries." },
  { icon: KeyRound, name: "Sessions (JWT)", how: "10-minute ES256-signed access token and a single-use refresh token, both in HttpOnly, Secure, SameSite=Strict cookies the page can’t read. Reusing an old refresh token signs that session out everywhere." },
  { icon: UserCog, name: "Authorization", how: "Deny by default: a route with no rule is refused. Customer and admin roles, and every message is checked against its owner. Someone else’s message looks exactly like one that doesn’t exist." },
  { icon: ScrollText, name: "Auditing", how: "Every sign-in, refusal and reset is logged without message text or IP addresses. Each row carries the hash of the one before, so editing or deleting a row is detectable." },
  { icon: Lock, name: "Encryption in transit", how: "HTTPS to every outside service with certificate checks on. Twilio webhooks are signed and verified." },
  { icon: ShieldCheck, name: "Encryption at rest", how: "Secrets on disk are sealed with AES-256-GCM and a rotating key ring. Message text never reaches disk at all: it lives in memory for the session." },
  { icon: VenetianMask, name: "Anonymization", how: "Phone numbers become keyed hashes, user IDs are random, and scam campaigns keep only fingerprints." },
  { icon: EyeOff, name: "Masking", how: "Links in the customer view are masked, tokens and keys are never logged, and SMS replies never repeat a scam’s link or number." },
  { icon: ClipboardList, name: "Personal information", how: "Names, phone numbers, account digits, addresses and links are redacted before the classifier, the AI or any tool sees a message. We never ask for an SSN, password or one-time code." },
];

/** `/security`: the nine pillars, and the live audit log for an admin. */
export function SecurityPage() {
  const authOn = useHealth()?.auth_enabled === true;
  const [me, setMe] = useState<Me>();
  const [audit, setAudit] = useState<AuditView>();

  useEffect(() => {
    if (!authOn) return;
    getMe()
      .then((user) => {
        setMe(user);
        if (user.role === "admin") {
          return fetch("/api/audit?limit=25", { credentials: "same-origin" })
            .then((r) => (r.ok ? (r.json() as Promise<AuditView>) : undefined))
            .then(setAudit);
        }
      })
      .catch(() => undefined);
  }, [authOn]);

  return (
    <Shell>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Security and privacy</p>
        <h1>How SentinelAI protects the people it protects</h1>
        <p className="cx-muted">
          Sign-in is {authOn ? "on" : "off for this demo (one demo customer)"}. Everything below is built and tested.
        </p>
      </div>
      <div className="cx-grid">
        {pillars.map(({ icon: Icon, name, how }) => (
          <article key={name} className="cx-card">
            <div className="cx-row-top">
              <Icon size={16} aria-hidden="true" />
              <strong>{name}</strong>
            </div>
            <p className="cx-muted">{how}</p>
          </article>
        ))}
      </div>
      {me?.role === "admin" && audit && (
        <section className="cx-card cx-audit">
          <div className="cx-row-top">
            <ScrollText size={16} aria-hidden="true" />
            <strong>Audit log</strong>
            <span className={`cx-chip ${audit.chain_intact ? "" : "cx-chip-bad"}`}>
              {audit.chain_intact ? "chain intact ✓" : `tampered at row ${audit.first_broken_id}`}
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>Outcome</th>
                <th>Who</th>
              </tr>
            </thead>
            <tbody>
              {audit.events.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.ts).toLocaleTimeString()}</td>
                  <td>{e.event}</td>
                  <td>{e.outcome}</td>
                  <td className="cx-mono">{e.actor.slice(0, 13)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </Shell>
  );
}
