import { useEffect } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  Layers3,
  Sparkles,
} from "lucide-react";
import { Brand, PhoneFrame } from "./components";
import Consent from "./screens/Consent";
import Inbox from "./screens/Inbox";
import Result, { ResultError } from "./screens/Result";
import Trail from "./screens/Trail";
import Privacy from "./screens/Privacy";
import Recovery from "./screens/Recovery";
import Campaigns from "./screens/Campaigns";
import Accuracy from "./screens/Accuracy";
import Gallery from "./screens/Gallery";
import type { ResultState, ScenarioId } from "./types";
const nav = [
  ["/consent", "A calm beginning"],
  ["/inbox", "Your messages"],
  ["/result", "A clear result"],
  ["/trail", "How we checked"],
  ["/privacy", "Privacy, made visible"],
  ["/recovery", "A way forward"],
  ["/campaigns", "The wider pattern"],
];
function PhoneExperience() {
  const location = useLocation();
  const [search] = useSearchParams();
  const scenario = (
    ["bank", "billing", "recovery"].includes(search.get("scenario") || "")
      ? search.get("scenario")
      : "bank"
  ) as ScenarioId;
  const state = search.get("state") || "";
  const resultState = (
    ["scam", "unsure", "safe", "mixed"].includes(state) ? state : "scam"
  ) as ResultState;
  const path = location.pathname;
  const screen =
    path === "/consent" ? (
      <Consent />
    ) : path === "/inbox" ? (
      <Inbox key={state} state={state} />
    ) : path === "/trail" ? (
      <Trail scenario={scenario} state={resultState} />
    ) : path === "/privacy" ? (
      <Privacy scenario={scenario} />
    ) : path === "/recovery" ? (
      <Recovery key={state} state={state || "intro"} />
    ) : path === "/campaigns" ? (
      <Campaigns state={state} />
    ) : state === "error" ? (
      <ResultError />
    ) : (
      <Result key={scenario + state} scenario={scenario} state={resultState} />
    );
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
        <nav aria-label="Prototype screens">
          {nav.map(([to, label], i) => (
            <NavLink
              to={to}
              key={to}
              className={({ isActive }) =>
                `stage-nav ${isActive ? "active" : ""}`
              }
            >
              <span>0{i + 1}</span>
              {label}
              <ChevronRight size={15} />
            </NavLink>
          ))}
        </nav>
      </aside>
      <PhoneFrame
        back={path !== "/consent" ? "/inbox" : undefined}
        label="SentinelAI interactive prototype"
      >
        {screen}
      </PhoneFrame>
      <aside className="stage-right">
        <span className="specimen-tag">
          <Sparkles size={14} />
          Steady / Prototype
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
          <Link to="/result">
            01 <span>The account-lock text</span>
            <ArrowUpRight size={15} />
          </Link>
          <Link to="/recovery">
            02 <span>“I entered my info”</span>
            <ArrowUpRight size={15} />
          </Link>
          <Link to="/result?scenario=billing">
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
          </p>
        </div>
      </aside>
    </main>
  );
}
export default function App() {
  const location = useLocation();
  useEffect(() => {
    document.title = `SentinelAI · ${location.pathname === "/gallery" ? "Screen gallery" : location.pathname === "/accuracy" ? "Accuracy" : "A little certainty"}`;
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="lab-header">
        <Link to="/" aria-label="SentinelAI prototype home">
          <Brand />
        </Link>
        <nav aria-label="Design lab">
          <NavLink to="/result">Prototype</NavLink>
          <NavLink to="/gallery">
            <Layers3 size={15} />
            Gallery
          </NavLink>
          <NavLink to="/accuracy">Accuracy</NavLink>
        </nav>
        <span className="lab-label">
          HACKUTD 2026 <span>DESIGN LAB</span>
        </span>
      </header>
      <div id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/gallery" element={<Gallery />} />
          <Route path="/accuracy" element={<Accuracy />} />
          <Route path="*" element={<PhoneExperience />} />
        </Routes>
      </div>
    </>
  );
}
