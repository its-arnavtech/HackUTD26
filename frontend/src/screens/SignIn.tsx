import { useState, type FormEvent } from "react";
import { browserSupportsWebAuthn, startAuthentication } from "@simplewebauthn/browser";
import { Fingerprint, KeyRound, LockKeyhole } from "lucide-react";
import { getCsrf, passkeyLoginOptions, passkeyLoginVerify, passwordLogin, totpLogin } from "../api";
import { ActionButton, PageTitle } from "../components";

type Step = "choose" | "password" | "code";

/**
 * Sign-in (L13), shown only when the API says auth is on.
 * A passkey first: it can't be phished, because the browser only signs for this site.
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
      const result = await passkeyLoginVerify(credential);
      if (result.signed_in) onSignedIn();
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

  const withCode = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const result = await totpLogin(code);
      setCode("");
      if (result.signed_in) onSignedIn();
    });
  };

  return (
    <div className="screen-pad signin-screen">
      <PageTitle eyebrow="Your account" description="Sign in to see your messages. We never ask for your bank password.">
        Welcome
        <br />
        back.
      </PageTitle>

      {step === "choose" && (
        <>
          {passkeys && (
            <ActionButton onClick={() => void withPasskey()} disabled={busy} icon={<Fingerprint size={21} />} arrow>
              Sign in with a passkey
            </ActionButton>
          )}
          <button className="text-button" onClick={() => setStep("password")} disabled={busy}>
            Use a password and code instead
          </button>
        </>
      )}

      {step === "password" && (
        <form className="signin-form" onSubmit={withPassword}>
          <label>
            Username
            <input
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              maxLength={64}
              required
            />
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
          <ActionButton type="submit" disabled={busy} icon={<KeyRound size={21} />} arrow>
            Continue
          </ActionButton>
          {passkeys && (
            <button type="button" className="text-button" onClick={() => setStep("choose")}>
              Use a passkey instead
            </button>
          )}
        </form>
      )}

      {step === "code" && (
        <form className="signin-form" onSubmit={withCode}>
          <label>
            6-digit code from your authenticator app
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              required
            />
          </label>
          <ActionButton type="submit" disabled={busy || code.length !== 6} icon={<LockKeyhole size={21} />} arrow>
            Sign in
          </ActionButton>
        </form>
      )}

      {problem && (
        <p className="signin-problem" role="alert">
          {problem}
        </p>
      )}
      <p className="quiet-note">Invite-only demo accounts. Synthetic data only.</p>
    </div>
  );
}
