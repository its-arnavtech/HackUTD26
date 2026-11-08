import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ArrowLeft, ArrowUpRight, ChartNoAxesCombined, ChevronRight, Fingerprint, Layers3, LifeBuoy, ListChecks, LockKeyhole, Menu, MessageSquareText, Network, ScanLine, Shield, ShieldCheck, Unplug, X } from "lucide-react";
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

export function apiModeLine(health?: Health): string | undefined {
  if (!health) return undefined;
  const routes = Object.values(health.mocked_routes);
  const mocked = routes.filter(Boolean).length;
  if (mocked === 0) return "Live API.";
  if (mocked === routes.length) return "Mock API responses.";
  return `Live API · ${mocked} of ${routes.length} routes on mocks.`;
}

/** Message-specific tabs keep the customer's current message in context. */
export function navigationFor(pathname: string) {
  const id = pathname.match(/^\/(?:result|trail|privacy|recovery)\/([^/]+)/)?.[1] ?? "msg_0001";
  return [
    { to: "/inbox", label: "Messages", icon: MessageSquareText, group: "Protection" },
    { to: `/result/${id}`, label: "Check result", icon: ShieldCheck, group: "Protection" },
    { to: `/trail/${id}`, label: "How we checked", icon: ListChecks, group: "Protection" },
    { to: `/recovery/${id}`, label: "Recovery", icon: LifeBuoy, group: "Protection" },
    { to: `/privacy/${id}`, label: "Privacy", icon: Fingerprint, group: "Insights" },
    { to: "/campaigns", label: "Scam patterns", icon: Network, group: "Insights" },
    { to: "/accuracy", label: "Accuracy", icon: ChartNoAxesCombined, group: "Insights" },
    { to: "/gallery", label: "Screen gallery", icon: Layers3, group: "Explore" },
    { to: "/consent", label: "Account connection", icon: Unplug, group: "Explore" },
  ];
}

function SupportTiles({ messageId }: { messageId: string }) {
  return <aside className="support-tiles" aria-label="Helpful resources">
    <section className="privacy-tile">
      <div className="tile-topline"><span className="eyebrow">Private by design</span><Fingerprint size={20} /></div>
      <div className="clay-lock" aria-hidden="true"><LockKeyhole size={38} /></div>
      <h2>Your details.<br />Still yours.</h2>
      <p>Personal details are redacted before a message reaches the AI.</p>
      <Link to={`/privacy/${messageId}`}>See what was shared <ArrowUpRight size={19} /></Link>
    </section>
    <section className="scenario-tile clay-panel">
      <div className="tile-topline"><h2>Explore the demo</h2><span className="small-tag">3 stories</span></div>
      <p className="tile-description">Different texts. Different checks.</p>
      <Link to="/result/msg_0001"><span className="scenario-number">01</span><span><strong>The account-lock text</strong><small>A bank impersonation attempt</small></span><ChevronRight size={17} /></Link>
      <Link to="/recovery/msg_0001"><span className="scenario-number">02</span><span><strong>Already clicked?</strong><small>A guided path to recovery</small></span><ChevronRight size={17} /></Link>
      <Link to="/result/msg_0003"><span className="scenario-number">03</span><span><strong>The overdue-bill text</strong><small>Check the claim against the bill</small></span><ChevronRight size={17} /></Link>
    </section>
    <section className="choice-note"><ShieldCheck size={23} /><p><strong>You stay in control.</strong><br />Every protective action starts with your tap.</p></section>
  </aside>;
}

function ProtectionWorkspace() {
  const { pathname } = useLocation();
  const isInbox = pathname === "/inbox";
  const messageId = pathname.match(/^\/(?:result|trail|privacy|recovery)\/([^/]+)/)?.[1] ?? "msg_0001";
  return <>
    {isInbox && <section className="welcome-banner" aria-label="Welcome to SentinelAI">
      <div className="welcome-copy">
        <p className="eyebrow"><span className="blue-dot" /> A little clarity. A lot less worry.</p>
        <h1>Pause the panic.<br /><span>Find your next step.</span></h1>
        <p>A suspicious text shouldn’t decide your day.<br className="desktop-break" /> Check the signs, understand the evidence, stay in control.</p>
        <Link to="/trail/msg_0001" className="welcome-link">See how a check works <ArrowUpRight size={18} /></Link>
      </div>
      <div className="shield-scene" aria-hidden="true">
        <div className="shield-orbit orbit-back" /><div className="shield-orbit orbit-front" />
        <span className="scene-dot dot-one" /><span className="scene-dot dot-two" /><div className="shield-plinth" />
        <div className="shield-sculpture"><Shield size={112} strokeWidth={1.25} /><LockKeyhole className="shield-key" size={35} /></div>
        <span className="scene-caption"><ScanLine size={14} /> Clarity before action</span>
      </div>
    </section>}
    <div className={`workspace-grid ${isInbox ? "workspace-inbox" : ""}`}>
      <section className="workspace-screen clay-panel" aria-label="SentinelAI demo">
        {!isInbox && pathname !== "/consent" && <Link to="/inbox" className="workspace-back"><ArrowLeft size={17} /> Back to messages</Link>}
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
      </section>
      <SupportTiles messageId={messageId} />
    </div>
  </>;
}

export default function App() {
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const nav = navigationFor(pathname);
  const current = nav.find(item => pathname.split("/")[1] === item.to.split("/")[1]);
  const health = useHealth();
  useEffect(() => {
    document.title = `SentinelAI · ${current?.label ?? "Your protection workspace"}`;
    window.scrollTo(0, 0);
    setMenuOpen(false);
  }, [pathname, current?.label]);
  useEffect(() => {
    if (!menuOpen) return;
    document.querySelector<HTMLAnchorElement>(".workspace-nav")?.focus();
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        document.getElementById("navigation-toggle")?.focus();
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [menuOpen]);
  return <div className="security-app">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className={`workspace-sidebar ${menuOpen ? "is-open" : ""}`} id="workspace-navigation">
      <Link className="sidebar-brand" to="/inbox" aria-label="SentinelAI demo home"><Brand /></Link>
      <p className="brand-caption">A clearer path through uncertainty.</p>
      <nav aria-label="Main navigation">
        {["Protection", "Insights", "Explore"].map(group => <div className="nav-group" key={group}>
          <p className="nav-group-label">{group}</p>
          {nav.filter(item => item.group === group).map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} onClick={() => { setMenuOpen(false); if (menuOpen) document.getElementById("main-content")?.focus(); }} className={({ isActive }) => `workspace-nav ${isActive || current?.label === label ? "active" : ""}`}>
            <Icon size={20} /><span>{label}</span><ChevronRight className="nav-chevron" size={15} />
          </NavLink>)}
        </div>)}
      </nav>
      <div className="sidebar-bottom"><div className="demo-emblem"><ShieldCheck size={21} /></div><div><strong>Made for peace of mind</strong><span>HackUTD 2026 · Demo</span></div></div>
    </aside>
    <div className="workspace-body">
      <header className="workspace-header">
        <button id="navigation-toggle" className="menu-toggle" aria-expanded={menuOpen} aria-controls="workspace-navigation" aria-label={menuOpen ? "Close navigation" : "Open navigation"} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={22} /> : <Menu size={22} />}</button>
        <div className="workspace-breadcrumb"><ShieldCheck size={18} /><Link className="mobile-brand" to="/inbox">Sentinel<span>AI</span></Link><span>Your workspace</span><ChevronRight size={14} /><strong>{current?.label ?? "Messages"}</strong></div>
        <div className="workspace-header-end"><span className="demo-pill"><span /> Synthetic demo</span><span className="workspace-avatar" aria-label="Demo workspace">S</span></div>
      </header>
      <main id="main-content" className="workspace-main" tabIndex={-1}>
        <Routes>
          <Route path="/gallery" element={<Gallery />} />
          <Route path="/accuracy" element={<AccuracyPage />} />
          <Route path="*" element={<ProtectionWorkspace />} />
        </Routes>
        <footer className="workspace-footer"><span><LockKeyhole size={14} /> Synthetic data. No live account.</span><span>{apiModeLine(health) ?? "Demo workspace"}</span></footer>
      </main>
    </div>
  </div>;
}
