import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ArrowLeft, Menu, X } from "lucide-react";
import type { Health } from "./api";
import { Brand } from "./components";
import { useHealth } from "./hooks";
import AccuracyPage from "./screens/AccuracyPage";
import CampaignView from "./screens/CampaignView";
import Consent from "./screens/Consent";
import Gallery from "./screens/Gallery";
import HowWeChecked from "./screens/HowWeChecked";
import Inbox from "./screens/Inbox";
import PrivacyPanel from "./screens/PrivacyPanel";
import Recovery from "./screens/Recovery";
import ResultCard from "./screens/ResultCard";

/** One line for the desk: whether the API is serving mocks, real code, or a mix (`/api/health`). */
export function apiModeLine(health?: Health): string | undefined {
  if (!health) return undefined;
  const routes = Object.values(health.mocked_routes);
  const mocked = routes.filter(Boolean).length;
  if (mocked === 0) return "Live API.";
  if (mocked === routes.length) return "Mock API responses.";
  return `Live API · ${mocked} of ${routes.length} routes on mocks.`;
}

type NavGroup = "Desk" | "Record" | "Bench";

/** Message-specific links keep the customer's current message in context. */
export function navigationFor(pathname: string) {
  const id = pathname.match(/^\/(?:result|trail|privacy|recovery)\/([^/]+)/)?.[1] ?? "msg_0001";
  return [
    { to: "/inbox", label: "Messages", group: "Desk" as NavGroup },
    { to: `/result/${id}`, label: "Check", group: "Desk" as NavGroup },
    { to: `/trail/${id}`, label: "Evidence", group: "Desk" as NavGroup },
    { to: `/recovery/${id}`, label: "Recovery", group: "Desk" as NavGroup },
    { to: `/privacy/${id}`, label: "Privacy", group: "Record" as NavGroup },
    { to: "/campaigns", label: "Patterns", group: "Record" as NavGroup },
    { to: "/accuracy", label: "Accuracy", group: "Bench" as NavGroup },
    { to: "/gallery", label: "Gallery", group: "Bench" as NavGroup },
    { to: "/consent", label: "Connect", group: "Bench" as NavGroup },
  ];
}

const stages = [
  {
    id: "redact",
    kicker: "01",
    title: "Redact",
    body: "Names, account digits, and phone numbers become tokens before a model or a tool sees the text.",
    rows: [
      ["Arrives as", "Linda, verify this sign-in"],
      ["Leaves as", "<PERSON>, verify this sign-in"],
    ],
  },
  {
    id: "investigate",
    kicker: "02",
    title: "Investigate",
    body: "The planner picks its own checks: the link, the sender, known patterns, and whether the account claim holds.",
    rows: [
      ["Looks at", "Link, sender, pattern, account claim"],
      ["Does not see", "Your name, number, or account digits"],
    ],
  },
  {
    id: "decide",
    kicker: "03",
    title: "You decide",
    body: "One verdict in words, the evidence behind it, and a single next step. Nothing is blocked, reported, or moved until you tap.",
    rows: [
      ["You see", "A verdict in words, never a percentage"],
      ["You choose", "The next step, or none"],
    ],
  },
];

const scenarios = [
  ["/result/msg_0001", "01", "Account-lock text", "A bank impersonation"],
  ["/recovery/msg_0001", "02", "Already clicked", "Activity since the text"],
  ["/result/msg_0003", "03", "Overdue-bill text", "The bill claim, checked"],
];

function SignalFlow() {
  const [stageId, setStageId] = useState(stages[0].id);
  const stage = stages.find((item) => item.id === stageId) ?? stages[0];
  return (
    <section className="signal-flow" aria-label="How a message is checked">
      <div className="signal-rail">
        {stages.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={item.id === stage.id}
            className={item.id === stage.id ? "is-on" : ""}
            onClick={() => setStageId(item.id)}
          >
            <span>{item.kicker}</span>
            {item.title}
          </button>
        ))}
        <i className="signal-beam" aria-hidden="true">
          <i />
        </i>
      </div>
      <div className="signal-readout" aria-live="polite">
        <p>{stage.body}</p>
        <dl>
          {stage.rows.map(([term, detail]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{detail}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

function Lede() {
  return (
    <section className="lede">
      <div className="lede-copy">
        <p className="eyebrow">
          <span className="live-pip" aria-hidden="true" /> Zero Day desk
        </p>
        <h1>
          The message is loud. <em>The evidence is specific.</em>
        </h1>
        <p>
          A suspicious text gets a minute of checking before it gets a minute of you. Personal details come off first.
        </p>
      </div>
      <SignalFlow />
    </section>
  );
}

export default function App() {
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const nav = navigationFor(pathname);
  const section = pathname.split("/")[1] || "inbox";
  const current = nav.find((item) => item.to.split("/")[1] === section);
  const health = useHealth();
  const isInbox = pathname === "/inbox";
  const wide = pathname === "/gallery" || pathname === "/accuracy";
  const showBack = /^\/(result|trail|privacy|recovery)(\/|$)/.test(pathname);

  useEffect(() => {
    document.title = `SentinelAI · ${current?.label ?? "Messages"}`;
    window.scrollTo(0, 0);
    setMenuOpen(false);
  }, [pathname, current?.label]);

  useEffect(() => {
    if (!menuOpen) return;
    document.querySelector<HTMLAnchorElement>("#site-navigation a")?.focus();
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        document.getElementById("navigation-toggle")?.focus();
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [menuOpen]);

  const closeMenu = () => {
    if (!menuOpen) return;
    setMenuOpen(false);
    document.getElementById("main-content")?.focus();
  };

  return (
    <div className="night">
      <div className="night-wash" aria-hidden="true" />
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="mast">
        <Link to="/inbox" className="mast-brand" aria-label="SentinelAI demo home">
          <Brand />
        </Link>
        <p className="mast-kicker">
          HackUTD 2026 <span>Zero Day</span>
        </p>
        <div className="mast-meta">
          <span className="demo-pill">
            <i /> Synthetic demo
          </span>
          <button
            id="navigation-toggle"
            className="menu-toggle"
            type="button"
            aria-expanded={menuOpen}
            aria-controls="site-navigation"
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </header>
      <nav id="site-navigation" className={`rail ${menuOpen ? "is-open" : ""}`} aria-label="Main navigation">
        {(["Desk", "Record", "Bench"] as const).map((group) => (
          <div className="rail-group" key={group}>
            <p className="rail-label">{group}</p>
            {nav
              .filter((item) => item.group === group)
              .map((item) => (
                <NavLink
                  key={item.label}
                  to={item.to}
                  onClick={closeMenu}
                  className={({ isActive }) => (isActive ? "active" : undefined)}
                >
                  <span className="rail-index" aria-hidden="true">
                    {String(nav.indexOf(item) + 1).padStart(2, "0")}
                  </span>
                  {item.label}
                </NavLink>
              ))}
          </div>
        ))}
      </nav>
      <main id="main-content" className={`night-main ${wide ? "is-wide" : ""}`} tabIndex={-1}>
        {isInbox && <Lede />}
        <div className={wide ? "bench" : "sheet"}>
          {showBack && (
            <Link to="/inbox" className="sheet-back">
              <ArrowLeft size={16} /> Messages
            </Link>
          )}
          <Routes>
            <Route path="/consent" element={<Consent />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/result/:messageId" element={<ResultCard />} />
            <Route path="/trail/:messageId" element={<HowWeChecked />} />
            <Route path="/privacy/:messageId?" element={<PrivacyPanel />} />
            <Route path="/recovery/:messageId?" element={<Recovery />} />
            <Route path="/campaigns" element={<CampaignView />} />
            <Route path="/gallery" element={<Gallery />} />
            <Route path="/accuracy" element={<AccuracyPage />} />
            <Route path="*" element={<Navigate to="/inbox" replace />} />
          </Routes>
          {isInbox && (
            <nav className="scenario-strip" aria-label="Demo scenarios">
              {scenarios.map(([to, index, title, detail]) => (
                <Link key={to} to={to}>
                  <span>{index}</span>
                  <strong>{title}</strong>
                  <small>{detail}</small>
                </Link>
              ))}
            </nav>
          )}
        </div>
        <footer className="night-footer">
          <span>Synthetic data. No live account.</span>
          <span>{apiModeLine(health) ?? "Demo desk"}</span>
        </footer>
      </main>
    </div>
  );
}
