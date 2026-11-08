import { useState } from "react";
import PhoneFrame from "./components/PhoneFrame";
import AccuracyPage from "./screens/AccuracyPage";
import CampaignView from "./screens/CampaignView";
import Consent from "./screens/Consent";
import HowWeChecked from "./screens/HowWeChecked";
import Inbox from "./screens/Inbox";
import PrivacyPanel from "./screens/PrivacyPanel";
import Recovery from "./screens/Recovery";
import ResultCard from "./screens/ResultCard";

// Scaffold shell: pick a placeholder screen. A7 replaces this with real navigation and /gallery.
const PHONE_SCREENS = {
  Consent,
  Inbox,
  "Result card": ResultCard,
  "How we checked": HowWeChecked,
  Privacy: PrivacyPanel,
  Recovery,
  Campaigns: CampaignView,
} as const;

type ScreenName = keyof typeof PHONE_SCREENS;

export default function App() {
  const [screen, setScreen] = useState<ScreenName>("Inbox");
  const Screen = PHONE_SCREENS[screen];

  return (
    <div className="flex min-h-screen flex-wrap items-start justify-center gap-10 p-8">
      <div className="flex flex-col gap-4">
        <nav className="flex max-w-[390px] flex-wrap gap-2" aria-label="Screens">
          {(Object.keys(PHONE_SCREENS) as ScreenName[]).map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setScreen(name)}
              className={`min-h-tap rounded-full px-4 ${name === screen ? "bg-ink text-white" : "bg-unsure-bg"}`}
            >
              {name}
            </button>
          ))}
        </nav>
        <PhoneFrame>
          <Screen />
        </PhoneFrame>
      </div>
      <section className="w-full max-w-xl rounded-2xl bg-white shadow">
        <AccuracyPage />
      </section>
    </div>
  );
}
