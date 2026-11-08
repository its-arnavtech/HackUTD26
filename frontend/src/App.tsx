import { useEffect } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ArrowUpRight, BookOpen, ChevronRight, Layers3, Sparkles } from "lucide-react";
import type { Health } from "./api";
import { AccountLine, AuthGate } from "./auth";
import Console, { ResultPage } from "./console/Console";
import SystemView from "./console/SystemView";
import { AccuracyShell, PatternsPage, SecurityPage } from "./console/Pages";
import { Brand, PhoneFrame } from "./components";
import { useHealth } from "./hooks";
import CampaignView from "./screens/CampaignView";
import Consent from "./screens/Consent";
import Gallery from "./screens/Gallery";
import HowWeChecked from "./screens/HowWeChecked";
import Inbox from "./screens/Inbox";
import PrivacyPanel from "./screens/PrivacyPanel";
import Recovery from "./screens/Recovery";
import ResultCard from "./screens/ResultCard";

const nav = [
  ["/consent", "A calm beginning"],
  ["/inbox", "Your messages"],
  ["/result/msg_0001", "A clear result"],
  ["/trail/msg_0001", "How we checked"],
  ["/privacy/msg_0001", "Privacy, made visible"],
  ["/recovery", "A way forward"],
  ["/campaigns", "The wider pattern"],
];

/** One line for the stage: whether the API is serving mocks, real code, or a mix (`/api/health`). */
export function apiModeLine(health?: Health): string | undefined {
  if (!health) return undefined;
  const routes = Object.values(health.mocked_routes);
  const mocked = routes.filter(Boolean).length;
  if (mocked === 0) return "Live API.";
  if (mocked === routes.length) return "Mock API responses.";
  return `Live API · ${mocked} of ${routes.length} routes on mocks.`;
}

function PhoneExperience() {
  const { pathname } = useLocation();
  const apiMode = apiModeLine(useHealth());
  return (
    <main className="stage-shell">
      <aside className="stage-left">
        <p className="eyebrow">Designed for a moment of worry</p>
        <h1>
          A little certainty.
          <br />A clear next step.
        </h1>
        <p className="stage-description">
          Scammers create urgency.
          <br />
          We create room to think.
        </p>
        <nav aria-label="Demo screens">
          {nav.map(([to, label], i) => (
            <NavLink to={to} key={to} className={({ isActive }) => `stage-nav ${isActive ? "active" : ""}`}>
              <span>0{i + 1}</span>
              {label}
              <ChevronRight size={15} />
            </NavLink>
          ))}
        </nav>
      </aside>
      <PhoneFrame back={pathname !== "/consent" && pathname !== "/inbox" ? "/inbox" : undefined} label="SentinelAI demo">
        <AuthGate>
        <Routes>
          <Route path="/consent" element={<Consent />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/result/:messageId" element={<ResultCard />} />
          <Route path="/trail/:messageId" element={<HowWeChecked />} />
          <Route path="/privacy/:messageId?" element={<PrivacyPanel />} />
          <Route path="/recovery/:messageId?" element={<Recovery />} />
          <Route path="/campaigns" element={<CampaignView />} />
          <Route path="*" element={<Navigate to="/inbox" replace />} />
        </Routes>
        </AuthGate>
      </PhoneFrame>
      <aside className="stage-right">
        <span className="specimen-tag">
          <Sparkles size={14} />
          Steady / Demo
        </span>
        <h2>
          Take a breath.
          <br />
          Then take a look.
        </h2>
        <p>
          One verdict in words.
          <br />A reason you can understand.
          <br />A choice that stays yours.
        </p>
        <div className="scenario-picker">
          <p className="eyebrow">Try the three scenarios</p>
          <Link to="/result/msg_0001">
            01 <span>The account-lock text</span>
            <ArrowUpRight size={15} />
          </Link>
          <Link to="/recovery/msg_0001">
            02 <span>“I entered my info”</span>
            <ArrowUpRight size={15} />
          </Link>
          <Link to="/result/msg_0003">
            03 <span>The overdue-bill text</span>
            <ArrowUpRight size={15} />
          </Link>
        </div>
        <div className="fixture-note">
          <BookOpen size={17} />
          <p>
            Authored demo scenarios.
            <br />
            Synthetic data. No live account.
            {apiMode && (
              <>
                <br />
                {apiMode}
              </>
            )}
          </p>
        </div>
        <AccountLine />
      </aside>
    </main>
  );
}

/** The original phone-frame demo (A7, A14 to A16), kept at its old URLs until Arnav signs off on the console. */
function ClassicApp() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = `SentinelAI · ${pathname === "/gallery" ? "Screen gallery" : pathname === "/accuracy" ? "Accuracy" : "A little certainty"}`;
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="lab-header">
        <Link to="/inbox" aria-label="SentinelAI demo home">
          <Brand />
        </Link>
        <nav aria-label="Demo">
          <NavLink to="/">Console</NavLink>
          <NavLink to="/inbox">Demo</NavLink>
          <NavLink to="/gallery">
            <Layers3 size={15} />
            Gallery
          </NavLink>
          <NavLink to="/accuracy">Accuracy</NavLink>
        </nav>
        <span className="lab-label">
          HACKUTD 2026 <span>SENTINELAI</span>
        </span>
      </header>
      <div id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/gallery" element={<Gallery />} />
          <Route path="*" element={<PhoneExperience />} />
        </Routes>
      </div>
    </>
  );
}

/** L14: the console is the default screen; the classic phone demo keeps its URLs (/inbox, /result/…, /gallery). */
export default function App() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (pathname === "/" || pathname.startsWith("/r/")) document.title = "SentinelAI · Console";
  }, [pathname]);
  return (
    <Routes>
      <Route path="/" element={<AuthGate><SystemView /></AuthGate>} />
      <Route path="/customer" element={<AuthGate><Console /></AuthGate>} />
      <Route path="/r/:messageId" element={<AuthGate><ResultPage /></AuthGate>} />
      <Route path="/patterns" element={<AuthGate><PatternsPage /></AuthGate>} />
      <Route path="/accuracy" element={<AuthGate><AccuracyShell /></AuthGate>} />
      <Route path="/security" element={<SecurityPage />} />
      <Route path="*" element={<ClassicApp />} />
    </Routes>
  );
}
