import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { PhoneFrame } from "../components";
import { checkedInbox, runningPoll } from "../fixtures";
import { newestFirst, withProgress } from "../hooks";
import AccuracyPage from "./AccuracyPage";
import CampaignView from "./CampaignView";
import Consent from "./Consent";
import HowWeChecked from "./HowWeChecked";
import { InboxView } from "./Inbox";
import PrivacyPanel from "./PrivacyPanel";
import Recovery from "./Recovery";
import ResultCard from "./ResultCard";

/** The overdue-bill text caught two steps into its check; the other rows are finished. */
function checkingInbox() {
  const poll = runningPoll("scenario3", 2);
  const items = checkedInbox().map((item) =>
    item.message_id === "msg_0003" ? withProgress({ ...item, verdict: null, confidence_words: null }, poll) : item,
  );
  return { items: newestFirst(items), progress: { msg_0003: poll } };
}

type GalleryItem = { id: string; group: string; label: string; detail: string; screen: ReactNode };

/** Every phone screen in every state, rendered from the mocks. Screens here never fetch. */
export const galleryItems: GalleryItem[] = [
  {
    id: "consent",
    group: "start",
    label: "01 · Consent",
    detail: "Read access, privacy, and a clear choice",
    screen: <Consent />,
  },
  {
    id: "inbox",
    group: "start",
    label: "02 · Inbox",
    detail: "Messages with verdicts in words",
    screen: <InboxView items={newestFirst(checkedInbox())} onCheckNew={() => undefined} />,
  },
  {
    id: "checking",
    group: "start",
    label: "03 · Checking",
    detail: "A new text, mid-check · held for visual review",
    screen: <InboxView {...checkingInbox()} />,
  },
  {
    id: "scam",
    group: "verdicts",
    label: "04 · Very likely a scam",
    detail: "Bank impersonation · authored scenario 1",
    screen: <ResultCard />,
  },
  {
    id: "unsure",
    group: "verdicts",
    label: "05 · We’re not sure",
    detail: "A clear limit on what we can confirm",
    screen: <ResultCard />,
  },
  {
    id: "safe",
    group: "verdicts",
    label: "06 · Likely safe",
    detail: "Green reserved for this verdict",
    screen: <ResultCard />,
  },
  {
    id: "mixed",
    group: "evidence",
    label: "07 · Mixed evidence",
    detail: "Conflicting signals lead to “not sure”",
    screen: <ResultCard />,
  },
  {
    id: "trail",
    group: "evidence",
    label: "08 · How we checked",
    detail: "Plan, findings, reasons · progressive motion",
    screen: <HowWeChecked />,
  },
  {
    id: "privacy",
    group: "evidence",
    label: "09 · Privacy",
    detail: "Redaction first · explicit model boundaries",
    screen: <PrivacyPanel />,
  },
  {
    id: "recovery",
    group: "recovery",
    label: "10 · I clicked",
    detail: "A calm start · authored scenario 2",
    screen: <Recovery />,
  },
  {
    id: "transfer",
    group: "recovery",
    label: "11 · Was this you?",
    detail: "A $900 transfer, 17 minutes after the text",
    screen: <Recovery />,
  },
  {
    id: "checklist",
    group: "recovery",
    label: "12 · Recovery checklist",
    detail: "Customer-controlled progress",
    screen: <Recovery />,
  },
  {
    id: "billing",
    group: "campaign",
    label: "13 · Fake billing",
    detail: "Paid bill evidence · authored scenario 3",
    screen: <ResultCard />,
  },
  {
    id: "billing-plan",
    group: "campaign",
    label: "14 · A different plan",
    detail: "Campaign → bill → public guidance",
    screen: <HowWeChecked />,
  },
  {
    id: "campaign",
    group: "campaign",
    label: "15 · Campaign pattern",
    detail: "Anonymous counts, templates, and guidance",
    screen: <CampaignView />,
  },
  {
    id: "replan",
    group: "more",
    label: "16 · Recovery re-plan",
    detail: "The customer’s tap changes the plan",
    screen: <HowWeChecked />,
  },
  {
    id: "complete",
    group: "more",
    label: "17 · Checklist complete",
    detail: "Progress is recorded, never inferred",
    screen: <Recovery />,
  },
  {
    id: "empty",
    group: "edge",
    label: "18 · Empty inbox",
    detail: "Quiet without an empty-dashboard feel",
    screen: <InboxView items={[]} state="empty" onCheckNew={() => undefined} />,
  },
  {
    id: "error",
    group: "edge",
    label: "19 · Check unavailable",
    detail: "No invented verdict · a retry path",
    screen: <ResultCard />,
  },
  {
    id: "empty-campaign",
    group: "edge",
    label: "20 · No campaigns",
    detail: "No patterns available yet",
    screen: <CampaignView />,
  },
  {
    id: "inbox-error",
    group: "edge",
    label: "21 · Messages unavailable",
    detail: "Nothing checked, nothing invented · a retry path",
    screen: <InboxView items={[]} state="error" onRetry={() => undefined} />,
  },
];

const filters = [
  ["all", "All screens"],
  ["start", "Start here"],
  ["verdicts", "Verdicts"],
  ["evidence", "Evidence & privacy"],
  ["recovery", "Recovery"],
  ["campaign", "Billing & campaigns"],
  ["more", "More states"],
  ["edge", "Empty & error"],
  ["accuracy", "Accuracy"],
];

export default function Gallery() {
  const [search, setSearch] = useSearchParams();
  const group = search.get("group") || "all";
  return (
    <main className="gallery-page">
      <header className="gallery-heading">
        <div>
          <p className="eyebrow">Steady · The complete screen collection</p>
          <h1>
            Every moment,
            <br />
            considered.
          </h1>
        </div>
        <p>
          A calm interface, even when the evidence isn’t.
          <br />
          {galleryItems.length} phone states + judge-facing accuracy · Synthetic fixtures
        </p>
      </header>
      <nav className="gallery-filters" aria-label="Gallery screens">
        {filters.map(([id, label]) => (
          <button key={id} aria-pressed={group === id} onClick={() => setSearch(id === "all" ? {} : { group: id })}>
            {label}
          </button>
        ))}
      </nav>
      <div className="gallery-grid">
        {galleryItems
          .filter((item) => group === "all" || item.group === group)
          .map((item) => (
            <article className="gallery-item" key={item.id}>
              <header>
                <h2>{item.label}</h2>
                <p>{item.detail}</p>
              </header>
              <PhoneFrame compact label={item.label} back={item.id !== "consent" ? "/inbox" : undefined}>
                <div key={item.id}>{item.screen}</div>
              </PhoneFrame>
            </article>
          ))}
      </div>
      {(group === "all" || group === "accuracy") && (
        <section className="gallery-accuracy" aria-label="Judge-facing accuracy screen">
          <AccuracyPage />
        </section>
      )}
      <footer className="gallery-footer">
        Deep ink for actions. Amber for caution. Green only for likely safe.
        <span>Source Sans 3 + Newsreader · Bundled locally</span>
      </footer>
    </main>
  );
}
