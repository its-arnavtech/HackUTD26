import { useSearchParams } from "react-router-dom";
import { PhoneFrame } from "../components";
import Consent from "./Consent";
import Inbox from "./Inbox";
import Result, { ResultError } from "./Result";
import Trail from "./Trail";
import Privacy from "./Privacy";
import Recovery from "./Recovery";
import Campaigns from "./Campaigns";
import Accuracy from "./Accuracy";
export const galleryItems = [
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
    screen: <Inbox />,
  },
  {
    id: "checking",
    group: "start",
    label: "03 · Checking",
    detail: "Checking fixture · held for visual review",
    screen: <Inbox state="checking" freezeChecking />,
  },
  {
    id: "scam",
    group: "verdicts",
    label: "04 · Very likely a scam",
    detail: "Bank impersonation · authored scenario 1",
    screen: <Result />,
  },
  {
    id: "unsure",
    group: "verdicts",
    label: "05 · We’re not sure",
    detail: "A clear limit on what we can confirm",
    screen: <Result state="unsure" />,
  },
  {
    id: "safe",
    group: "verdicts",
    label: "06 · Likely safe",
    detail: "Green reserved for this verdict",
    screen: <Result state="safe" />,
  },
  {
    id: "mixed",
    group: "evidence",
    label: "07 · Mixed evidence",
    detail: "Conflicting signals lead to “not sure”",
    screen: <Result state="mixed" />,
  },
  {
    id: "trail",
    group: "evidence",
    label: "08 · How we checked",
    detail: "Plan, findings, reasons · progressive motion",
    screen: <Trail />,
  },
  {
    id: "privacy",
    group: "evidence",
    label: "09 · Privacy",
    detail: "Redaction first · explicit model boundaries",
    screen: <Privacy />,
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
    screen: <Recovery state="transfer" />,
  },
  {
    id: "checklist",
    group: "recovery",
    label: "12 · Recovery checklist",
    detail: "Customer-controlled progress",
    screen: <Recovery state="checklist" />,
  },
  {
    id: "billing",
    group: "campaign",
    label: "13 · Fake billing",
    detail: "Paid bill evidence · authored scenario 3",
    screen: <Result scenario="billing" />,
  },
  {
    id: "billing-plan",
    group: "campaign",
    label: "14 · A different plan",
    detail: "Campaign → bill → public guidance",
    screen: <Trail scenario="billing" />,
  },
  {
    id: "campaign",
    group: "campaign",
    label: "15 · Campaign pattern",
    detail: "Anonymous counts, templates, and guidance",
    screen: <Campaigns state="detail" />,
  },
  {
    id: "replan",
    group: "more",
    label: "16 · Recovery re-plan",
    detail: "The customer’s tap changes the plan",
    screen: <Trail scenario="recovery" />,
  },
  {
    id: "complete",
    group: "more",
    label: "17 · Checklist complete",
    detail: "Progress is recorded, never inferred",
    screen: <Recovery state="complete" />,
  },
  {
    id: "empty",
    group: "edge",
    label: "18 · Empty inbox",
    detail: "Quiet without an empty-dashboard feel",
    screen: <Inbox state="empty" />,
  },
  {
    id: "error",
    group: "edge",
    label: "19 · Check unavailable",
    detail: "No invented verdict · a retry path",
    screen: <ResultError />,
  },
  {
    id: "empty-campaign",
    group: "edge",
    label: "20 · No campaigns",
    detail: "No patterns available yet",
    screen: <Campaigns state="empty" />,
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
          20 phone states + judge-facing accuracy · Synthetic fixtures
        </p>
      </header>
      <nav className="gallery-filters" aria-label="Gallery screens">
        {filters.map(([id, label]) => (
          <button
            key={id}
            aria-pressed={group === id}
            onClick={() => setSearch(id === "all" ? {} : { group: id })}
          >
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
              <PhoneFrame
                compact
                label={item.label}
                back={item.id !== "consent" ? "/inbox" : undefined}
              >
                <div key={item.id}>{item.screen}</div>
              </PhoneFrame>
            </article>
          ))}
      </div>
      {(group === "all" || group === "accuracy") && (
        <section
          className="gallery-accuracy"
          aria-label="Judge-facing accuracy screen"
        >
          <Accuracy />
        </section>
      )}
      <footer className="gallery-footer">
        Deep ink for actions. Amber for caution. Green only for likely safe.
        <span>Source Sans 3 + Newsreader · Bundled locally</span>
      </footer>
    </main>
  );
}
