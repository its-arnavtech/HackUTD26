import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import type { Health } from "./api";
import { AccountLine, AuthGate } from "./auth";
import { Brand } from "./components";
import Connect from "./console/Connect";
import Console, { ResultPage } from "./console/Console";
import { PatternsPage, SecurityPage } from "./console/Pages";
import SystemView from "./console/SystemView";
import { useHealth } from "./hooks";
import {
  holdScroll,
  scrollToElement,
  scrollToTop,
  useReveal,
  useScrollProgress,
  useSmoothScroll,
  useTuckedOnScroll,
} from "./motion";
import AccuracyPage from "./screens/AccuracyPage";
import CampaignView from "./screens/CampaignView";
import Consent from "./screens/Consent";
import Gallery from "./screens/Gallery";
import HowWeChecked from "./screens/HowWeChecked";
import Inbox from "./screens/Inbox";
import PrivacyPanel from "./screens/PrivacyPanel";
import Recovery from "./screens/Recovery";
import ResultCard from "./screens/ResultCard";

/** One line for the colophon: whether the API is serving mocks, real code, or a mix (`/api/health`). */
export function apiModeLine(health?: Health): string | undefined {
  if (!health) return undefined;
  const routes = Object.values(health.mocked_routes);
  const mocked = routes.filter(Boolean).length;
  if (mocked === 0) return "Live API.";
  if (mocked === routes.length) return "Mock API responses.";
  return `Live API · ${mocked} of ${routes.length} routes on mocks.`;
}

type NavGroup = "Start here" | "This message" | "Behind it";

/** Message-specific links keep the customer's current message in context. */
export function navigationFor(pathname: string) {
  const id = pathname.match(/^\/(?:result|trail|privacy|recovery)\/([^/]+)/)?.[1] ?? "msg_0001";
  return [
    { to: "/inbox", label: "Messages", group: "Start here" as NavGroup, note: "Today’s texts and what we found" },
    { to: `/result/${id}`, label: "Check", group: "This message" as NavGroup, note: "The verdict, in words" },
    { to: `/trail/${id}`, label: "Evidence", group: "This message" as NavGroup, note: "Every check, and why it ran" },
    { to: `/recovery/${id}`, label: "Recovery", group: "This message" as NavGroup, note: "If you already tapped the link" },
    { to: `/privacy/${id}`, label: "Privacy", group: "This message" as NavGroup, note: "What we never saw" },
    { to: "/campaigns", label: "Patterns", group: "Behind it" as NavGroup, note: "The same scam, sent to many" },
    { to: "/accuracy", label: "Accuracy", group: "Behind it" as NavGroup, note: "How often we’re right" },
    { to: "/gallery", label: "Gallery", group: "Behind it" as NavGroup, note: "Every screen, every state" },
    { to: "/consent", label: "Connect", group: "Behind it" as NavGroup, note: "Linking an account" },
  ];
}

/** The four views of one message, as a quiet line of links under the page. */
const folio = [
  ["result", "The verdict"],
  ["trail", "How we checked"],
  ["privacy", "What we never saw"],
  ["recovery", "If you clicked"],
] as const;

const stages = [
  {
    id: "redact",
    title: "Redact",
    body: "Names, account digits, and phone numbers become tokens before a model or a tool sees the text.",
    rows: [
      ["Arrives as", "Linda, verify this sign-in"],
      ["Leaves as", "<PERSON>, verify this sign-in"],
    ],
  },
  {
    id: "investigate",
    title: "Investigate",
    body: "The planner picks its own checks: the link, the sender, known patterns, and whether the account claim holds.",
    rows: [
      ["Looks at", "Link, sender, pattern, account claim"],
      ["Does not see", "Your name, number, or account digits"],
    ],
  },
  {
    id: "decide",
    title: "You decide",
    body: "One verdict in words, the evidence behind it, and a single next step. Nothing is blocked, reported, or moved until you tap.",
    rows: [
      ["You see", "A verdict in words, never a percentage"],
      ["You choose", "The next step, or none"],
    ],
  },
];

function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <p className="hero-kicker">SentinelAI, built at HackUTD 2026</p>
      <h1 id="hero-title" className="hero-title">
        <span className="line">
          <span>A second look,</span>
        </span>
        <span className="line">
          <span>
            before you <em>tap.</em>
          </span>
        </span>
      </h1>
      <div className="hero-aside">
        <p>
          SentinelAI reads a worrying text the way a careful friend would. It checks the link, the sender, and your
          actual account, then tells you in plain words what it found. Your name and numbers come off before anything
          else sees it.
        </p>
        <a
          className="hero-cue"
          href="#how"
          onClick={(event) => {
            event.preventDefault();
            scrollToElement("how");
          }}
        >
          How a check works
        </a>
      </div>
    </section>
  );
}

/** Where to start, as a sentence rather than a row of tiles. */
function Starts() {
  return (
    <section className="starts" aria-label="Demo scenarios">
      <p className="kicker">Where to start</p>
      <p className="starts-sentence">
        Open <Link to="/result/msg_0001">a text claiming your bank account is locked</Link>, see what happens{" "}
        <Link to="/recovery/msg_0001">after someone has already tapped the link</Link>, or check{" "}
        <Link to="/result/msg_0003">a bill reminder that turns out to be paid</Link>.
      </p>
    </section>
  );
}

function Method() {
  const ref = useRef<HTMLElement>(null);
  useScrollProgress(ref);
  return (
    <section className="method" id="how" ref={ref} aria-labelledby="method-title">
      <div className="method-head">
        <p className="kicker">How a check works</p>
        <h2 id="method-title">Three things happen before you see a verdict.</h2>
      </div>
      <ol className="method-steps">
        <span className="method-line" aria-hidden="true">
          <i />
        </span>
        {stages.map((stage, i) => (
          <li className="method-step" key={stage.id}>
            <span className="method-count" aria-hidden="true">
              {["One", "Two", "Three"][i]}
            </span>
            <h3>{stage.title}.</h3>
            <p>{stage.body}</p>
            <dl>
              {stage.rows.map(([term, detail]) => (
                <div key={term}>
                  <dt>{term}</dt>
                  <dd>{detail}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ol>
    </section>
  );
}

function MessageFolio({ pathname }: { pathname: string }) {
  const match = pathname.match(/^\/(result|trail|privacy|recovery)\/([^/]+)/);
  if (!match) return null;
  const [, view, id] = match;
  return (
    <nav className="folio" aria-label="This message">
      {folio.map(([path, label]) => (
        <Link key={path} to={`/${path}/${id}`} aria-current={path === view ? "page" : undefined}>
          {label}
        </Link>
      ))}
    </nav>
  );
}

function Desk() {
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const nav = navigationFor(pathname);
  const section = pathname.split("/")[1] || "inbox";
  const current = nav.find((item) => item.to.split("/")[1] === section);
  const health = useHealth();
  const isInbox = pathname === "/inbox";
  const wide = pathname === "/gallery" || pathname === "/accuracy";
  const showBack = /^\/(result|trail|privacy|recovery)(\/|$)/.test(pathname);
  const mainRef = useRef<HTMLElement>(null);
  const { tucked, scrolled } = useTuckedOnScroll();

  useSmoothScroll();
  useReveal(mainRef, pathname);

  useEffect(() => {
    document.title = `SentinelAI · ${current?.label ?? "Messages"}`;
    scrollToTop();
    setMenuOpen(false);
  }, [pathname, current?.label]);

  useEffect(() => {
    holdScroll(menuOpen);
    if (!menuOpen) return;
    document.querySelector<HTMLAnchorElement>("#site-navigation a")?.focus();
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        document.getElementById("navigation-toggle")?.focus();
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => {
      window.removeEventListener("keydown", onEscape);
      holdScroll(false);
    };
  }, [menuOpen]);

  const closeMenu = () => {
    if (!menuOpen) return;
    setMenuOpen(false);
    document.getElementById("main-content")?.focus();
  };

  const groups: NavGroup[] = ["Start here", "This message", "Behind it"];

  return (
    <div className={`desk ${menuOpen ? "index-open" : ""}`}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className={`mast ${tucked && !menuOpen ? "is-tucked" : ""} ${scrolled ? "is-scrolled" : ""}`}>
        <Link to="/inbox" className="mast-brand" aria-label="SentinelAI demo home" onClick={closeMenu}>
          <Brand />
        </Link>
        <p className="mast-where" aria-hidden="true">
          <span key={current?.label}>{current?.label ?? "Messages"}</span>
        </p>
        <button
          id="navigation-toggle"
          className="index-toggle"
          type="button"
          aria-expanded={menuOpen}
          aria-controls="site-navigation"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="index-word" aria-hidden="true">
            <span>Index</span>
            <span>Close</span>
          </span>
          <span className="index-glyph" aria-hidden="true">
            <i />
            <i />
          </span>
        </button>
      </header>

      <div id="site-navigation" className={`index ${menuOpen ? "is-open" : ""}`} inert={!menuOpen}>
        <nav className="index-inner" aria-label="Main navigation">
          {groups.map((group, g) => (
            <div className="index-group" key={group} style={{ "--g": g } as CSSProperties}>
              <p className="index-label">{group}</p>
              <ul>
                {nav
                  .filter((item) => item.group === group)
                  .map((item, i) => (
                    <li key={item.label} style={{ "--i": i } as CSSProperties}>
                      <NavLink
                        to={item.to}
                        onClick={closeMenu}
                        aria-label={item.label}
                        aria-describedby={`index-note-${i}-${g}`}
                        className={({ isActive }) => (isActive ? "active" : undefined)}
                      >
                        <span className="index-link">{item.label}</span>
                        <span className="index-note" id={`index-note-${i}-${g}`}>
                          {item.note}
                        </span>
                      </NavLink>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </nav>
        <p className="index-foot">
          <span>{apiModeLine(health) ?? "Demo desk"}</span>
          <Link to="/system" onClick={closeMenu}>
            System view
          </Link>
        </p>
      </div>

      <main
        id="main-content"
        ref={mainRef}
        className={`desk-main ${wide ? "is-wide" : ""} ${isInbox ? "is-home" : ""}`}
        tabIndex={-1}
      >
        {isInbox && <Hero />}
        <div className={wide ? "bench page" : "sheet page"} key={pathname}>
          {showBack && (
            <Link to="/inbox" className="sheet-back">
              <ArrowLeft size={15} strokeWidth={1.75} /> All messages
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
          <MessageFolio pathname={pathname} />
        </div>
        {isInbox && (
          <>
            <Starts />
            <Method />
          </>
        )}
        <footer className="colophon">
          <p className="colophon-line">
            Take a breath. <em>Then take a look.</em>
          </p>
          <div className="colophon-meta">
            <span>Synthetic data. No live account.</span>
            <span>{apiModeLine(health) ?? "Demo desk"}</span>
            <Link to="/system">System view</Link>
            <AccountLine />
          </div>
        </footer>
      </main>
    </div>
  );
}

/** The desk is the front door. The live console (system, check-any-message, connect) sits beside it. */
export default function App() {
  return (
    <Routes>
      <Route path="/system" element={<AuthGate><SystemView /></AuthGate>} />
      <Route path="/customer" element={<AuthGate><Console /></AuthGate>} />
      <Route path="/r/:messageId" element={<AuthGate><ResultPage /></AuthGate>} />
      <Route path="/patterns" element={<AuthGate><PatternsPage /></AuthGate>} />
      <Route path="/connect" element={<AuthGate><Connect /></AuthGate>} />
      <Route path="/security" element={<SecurityPage />} />
      <Route path="*" element={<AuthGate><Desk /></AuthGate>} />
    </Routes>
  );
}
