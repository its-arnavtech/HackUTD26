import { useCallback, useEffect, useState, type ReactNode } from "react";
import { startRegistration } from "@simplewebauthn/browser";
import { SIGNED_OUT_EVENT, getMe, logout, passkeyRegisterOptions, passkeyRegisterVerify } from "./api";
import { useHealth, useHealthState } from "./hooks";
import SignIn from "./screens/SignIn";
import type { Me } from "./types";

type State = { kind: "checking" } | { kind: "signed_out" } | { kind: "signed_in"; me: Me };

/** Fired by the gate after a successful sign-in, so other parts (the account line) refresh. */
export const SIGNED_IN_EVENT = "sentinel:signed-in";

/**
 * Shows sign-in when the API has auth on (L13) and there's no session; otherwise the children.
 * Nothing behind the gate mounts (or calls the API) until `/api/health` has answered. With auth
 * off (the default), or if health can't be reached, it renders the children unchanged, so the
 * demo and its offline states behave exactly as before.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { health, settled } = useHealthState();
  const authOn = health?.auth_enabled === true;
  const [state, setState] = useState<State>({ kind: "checking" });

  const check = useCallback(() => {
    getMe()
      .then((me) => {
        setState({ kind: "signed_in", me });
        window.dispatchEvent(new Event(SIGNED_IN_EVENT));
      })
      .catch(() => setState({ kind: "signed_out" }));
  }, []);

  useEffect(() => {
    if (!authOn) return;
    check();
    const onSignedOut = () => setState({ kind: "signed_out" });
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
  }, [authOn, check]);

  if (!settled) {
    return (
      <div className="loading-screen" role="status">
        Loading…
      </div>
    );
  }
  if (!authOn) return <>{children}</>;
  if (state.kind === "checking") {
    return (
      <div className="loading-screen" role="status">
        Checking your session…
      </div>
    );
  }
  if (state.kind === "signed_out") return <SignIn onSignedIn={check} />;
  return <>{children}</>;
}

/** "Signed in as …", add a passkey, sign out. Renders nothing when auth is off. Never shows a token. */
export function AccountLine({ compact = false }: { compact?: boolean }) {
  const authOn = useHealth()?.auth_enabled === true;
  const [me, setMe] = useState<Me>();
  const [note, setNote] = useState<string>();

  useEffect(() => {
    if (!authOn) return;
    const load = () => getMe().then(setMe).catch(() => setMe(undefined));
    const clear = () => setMe(undefined);
    load();
    window.addEventListener(SIGNED_IN_EVENT, load);
    window.addEventListener(SIGNED_OUT_EVENT, clear);
    return () => {
      window.removeEventListener(SIGNED_IN_EVENT, load);
      window.removeEventListener(SIGNED_OUT_EVENT, clear);
    };
  }, [authOn]);

  if (!authOn || !me) return null;

  const addPasskey = async () => {
    setNote(undefined);
    try {
      const optionsJSON = await passkeyRegisterOptions();
      const credential = await startRegistration({ optionsJSON });
      setMe(await passkeyRegisterVerify(credential));
      setNote("Passkey added. Use it next time you sign in.");
    } catch {
      setNote("The passkey wasn’t added.");
    }
  };

  const signOut = async () => {
    try {
      await logout();
    } finally {
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
      setMe(undefined);
    }
  };

  if (compact) {
    return (
      <div className="cx-account">
        <span>
          {me.display_name}
          {me.role === "admin" ? " · admin" : ""}
        </span>
        {me.passkeys === 0 && (
          <button className="cx-link-button" onClick={() => void addPasskey()}>
            Add passkey
          </button>
        )}
        <button className="cx-link-button" onClick={() => void signOut()}>
          Sign out
        </button>
        {note && <span className="cx-muted" role="status">{note}</span>}
      </div>
    );
  }

  return (
    <div className="account-line">
      <p>
        Signed in as <strong>{me.display_name}</strong>
        {me.role === "admin" ? " (admin)" : ""} · {me.passkeys > 0 ? "passkey on" : "no passkey yet"}
      </p>
      <div>
        <button className="text-button" onClick={() => void addPasskey()}>
          Add a passkey
        </button>
        <button className="text-button" onClick={() => void signOut()}>
          Sign out
        </button>
      </div>
      {note && <p role="status">{note}</p>}
    </div>
  );
}
