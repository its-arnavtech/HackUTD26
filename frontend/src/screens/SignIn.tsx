import { useState, type FormEvent } from "react";
import { browserSupportsWebAuthn, startAuthentication } from "@simplewebauthn/browser";
import { EyeOff, Fingerprint, HandHeart, KeyRound, ShieldCheck } from "lucide-react";
import { getCsrf, passkeyLoginOptions, passkeyLoginVerify, passwordLogin, totpLogin } from "../api";

type Step = "choose" | "password" | "code";

/**
 * Full-page sign-in (L13/L14), shown only when the API says auth is on.
 * Passkey first: it can't be phished, because the browser only signs for this site.
 * Password plus a 6-digit authenticator code is the fallback. Accounts are invite-only.
 */
export default function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [step, setStep] = useState<Step>("choose");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const passkeys = typeof window !== "undefined" && browserSupportsWebAuthn();

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setProblem(undefined);
    try {
      await getCsrf();
      await action();
    } catch {
      // One message for every failure: the server never says which part was wrong.
      setProblem("That didn’t work. Check your details and try again, or wait 15 minutes after many tries.");
    } finally {
      setBusy(false);
    }
  }

  const withPasskey = () =>
    run(async () => {
      const optionsJSON = await passkeyLoginOptions();
      const credential = await startAuthentication({ optionsJSON });
      if ((await passkeyLoginVerify(credential)).signed_in) onSignedIn();
    });

  const withPassword = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const result = await passwordLogin({ username, password });
      setPassword("");
      if (result.mfa_required) setStep("code");
      else if (result.signed_in) onSignedIn();
    });
  };

  const submitCode = (value: string) =>
    run(async () => {
      const result = await totpLogin(value);
      setCode("");
      if (result.signed_in) onSignedIn();
    });

  return (
    <div className="cx cx-signin">
      <section className="cx-signin-intro">
        <span className="cx-brand">
          <ShieldCheck size={22} aria-hidden="true" /> SentinelAI
        </span>
        <h1>A second opinion before you tap.</h1>
        <ul>
          <li>
            <KeyRound size={18} aria-hidden="true" /> We never ask for your SSN, bank password or one-time codes.
          </li>
          <li>
            <EyeOff size={18} aria-hidden="true" /> Personal details are hidden before any AI sees a message.
          </li>
          <li>
            <HandHeart size={18} aria-hidden="true" /> Nothing happens without your tap. We never move money.
          </li>
        </ul>
      </section>

      <section className="cx-signin-card" aria-label="Sign in">
        <h2>{step === "code" ? "Enter your code" : "Sign in"}</h2>

        {step === "choose" && (
          <>
            {passkeys && (
              <button className="cx-button cx-button-primary cx-button-block" onClick={() => void withPasskey()} disabled={busy}>
                <Fingerprint size={18} aria-hidden="true" /> Sign in with a passkey
              </button>
            )}
            <p className="cx-muted cx-small">Uses Face ID, Touch ID, Windows Hello or your phone.</p>
            <button className="cx-link-button" onClick={() => setStep("password")} disabled={busy}>
              Use a password and code instead
            </button>
          </>
        )}

        {step === "password" && (
          <form className="cx-form" onSubmit={withPassword}>
            <label>
              Username
              <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={64} required autoFocus />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={256}
                required
              />
            </label>
            <button type="submit" className="cx-button cx-button-primary cx-button-block" disabled={busy}>
              Continue
            </button>
            {passkeys && (
              <button type="button" className="cx-link-button" onClick={() => setStep("choose")}>
                Use a passkey instead
              </button>
            )}
          </form>
        )}

        {step === "code" && (
          <form
            className="cx-form"
            onSubmit={(e) => {
              e.preventDefault();
              void submitCode(code);
            }}
          >
            <label>
              6-digit code from your authenticator app
              <input
                className="cx-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                value={code}
                autoFocus
                onChange={(e) => {
                  const next = e.target.value.replace(/\D/g, "").slice(0, 6);
                  setCode(next);
                  if (next.length === 6 && !busy) void submitCode(next); // auto-advance
                }}
                required
              />
            </label>
            <button type="submit" className="cx-button cx-button-primary cx-button-block" disabled={busy || code.length !== 6}>
              Sign in
            </button>
          </form>
        )}

        {problem && (
          <p className="cx-alert" role="alert">
            {problem}
          </p>
        )}
        <p className="cx-muted cx-small">Invite-only demo accounts. Synthetic data only.</p>
      </section>
    </div>
  );
}
