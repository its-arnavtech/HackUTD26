import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { AccountLine } from "../auth";
import { useHealth } from "../hooks";

/** Live / Replay / Mocks, from `/api/health`. */
export function ModeBadge() {
  const health = useHealth();
  if (!health) return null;
  const mocked = Object.values(health.mocked_routes).filter(Boolean).length;
  const label = mocked === Object.keys(health.mocked_routes).length ? "Mock data" : health.demo_mode === "replay" ? "Replay" : "Live";
  return (
    <span className={`cx-badge cx-badge-${label === "Live" ? "live" : "muted"}`}>
      <span className="cx-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

const links: [string, string][] = [
  ["/system", "System"],
  ["/customer", "Customer view"],
  ["/connect", "Plug into any system"],
  ["/agent-accuracy", "Agent accuracy"],
  ["/waves", "Scam waves"],
  ["/patterns", "Scam patterns"],
  ["/model-accuracy", "Classifier accuracy"],
  ["/safety", "Safety center"],
  ["/privacy-center", "Privacy center"],
  ["/security", "Security"],
];

/** The page frame for the new screens: brand, nav, mode, account. */
export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="cx">
      <header className="cx-header">
        <NavLink to="/system" className="cx-brand" aria-label="SentinelAI console">
          <ShieldCheck size={22} aria-hidden="true" />
          SentinelAI
        </NavLink>
        <nav className="cx-nav" aria-label="Main">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/system"} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="cx-header-right">
          <ModeBadge />
          <AccountLine compact />
        </div>
      </header>
      <main id="main-content" className={`cx-main ${wide ? "cx-main-wide" : ""}`} tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
