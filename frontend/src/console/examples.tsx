// L15e: one-click demo examples (spec section 13) and a compact Safety Center.
// All messages are synthetic. Same console frame and .cx tokens; no new visual design.
import { BookOpen, Briefcase, CircleAlert, KeyRound, Landmark, Package, TrendingUp, Users } from "lucide-react";
import { Shell } from "./Shell";

export interface Example {
  id: string;
  label: string;
  sender: string;
  text: string;
  /** What the right answer is; undefined for the ambiguous one, where "not sure" is the honest result. */
  truth?: { category: string; is_scam: boolean };
}

export const EXAMPLES: Example[] = [
  {
    id: "bank",
    label: "Bank account suspension",
    sender: "+18885550111",
    text: "Chase: URGENT. Your account will be suspended in 30 minutes. Verify your account now at chase-account-verify.com",
    truth: { category: "bank_impersonation", is_scam: true },
  },
  {
    id: "otp",
    label: "One-time-code theft",
    sender: "+18885550112",
    text: "Amazon: We are refunding your $89.99 order. To receive it, reply with the 6-digit code we just texted you.",
    truth: { category: "account_security", is_scam: true },
  },
  {
    id: "delivery",
    label: "Fake delivery fee",
    sender: "+18885550113",
    text: "UPS: Your parcel is held at our depot. Pay the $1.99 redelivery fee at ups-parcel-redelivery.com within 24 hours.",
    truth: { category: "delivery_scam", is_scam: true },
  },
  {
    id: "investment",
    label: "Guaranteed investment",
    sender: "+18885550114",
    text: "Wells Fargo Investments: guaranteed 20% monthly returns on crypto. Only 5 spots left tonight. Join at wellsfargo-crypto-invest.com",
    truth: { category: "investment", is_scam: true },
  },
  {
    id: "legit",
    label: "Genuine Capital One alert",
    sender: "227898",
    text: "Capital One: A purchase of $42.17 at H-E-B was made on your Venture card. If this wasn't you, call the number on the back of your card.",
    truth: { category: "legit", is_scam: false },
  },
  {
    id: "ambiguous",
    label: "Ambiguous: should be “not sure”",
    sender: "55123",
    text: "Reminder: your appointment is tomorrow at 3 PM. Reply C to confirm or R to reschedule.",
  },
];

export function ExampleButtons({ busy, onRun }: { busy: boolean; onRun: (example: Example) => void }) {
  return (
    <div className="sx-examples" role="group" aria-label="Demo examples">
      <span className="cx-muted cx-small">Try an example:</span>
      {EXAMPLES.map((e) => (
        <button key={e.id} className="cx-button" disabled={busy} onClick={() => onRun(e)}>
          {e.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Safety Center
// ---------------------------------------------------------------------------

const TOPICS: { icon: typeof Landmark; name: string; how: string; signs: string[]; example: string; protect: string[]; already: string }[] = [
  {
    icon: Landmark,
    name: "Bank impersonation",
    how: "A text that looks like your bank says your account is locked or a payment failed, and sends you to a fake sign-in page.",
    signs: ["A deadline (“within 30 minutes”)", "A link to a site that isn’t your bank’s own", "A request to “verify” your login"],
    example: "Chase: Your account will be suspended. Verify now at chase-account-verify.com",
    protect: ["Open your bank’s app yourself instead of tapping the link", "Call the number on the back of your card"],
    already: "Change your password in the official app and call your bank now. Ask them to check for new payees and transfers.",
  },
  {
    icon: KeyRound,
    name: "One-time-code theft",
    how: "The scammer triggers a real security code to your phone, then asks you to read it back, which lets them into your account.",
    signs: ["Anyone asking you to share a code you just received", "A “refund” or “prize” that needs a code", "Pressure to reply quickly"],
    example: "Amazon: To receive your refund, reply with the 6-digit code we just texted you.",
    protect: ["Never share a one-time code, even with someone who says they’re the company", "Real companies never ask for it"],
    already: "Contact the company through its official app, change your password and sign out other devices.",
  },
  {
    icon: Package,
    name: "Fake delivery",
    how: "A text claims a package is held and asks for a small fee. The page steals your card details.",
    signs: ["A tiny fee ($1.99) for redelivery", "A link that isn’t the carrier’s own website", "You weren’t expecting a parcel"],
    example: "UPS: Your parcel is held. Pay the $1.99 fee at ups-parcel-redelivery.com",
    protect: ["Track parcels in the retailer’s or carrier’s own app", "Type the carrier’s address yourself"],
    already: "Call your card company on the number on the card and ask them to block the card.",
  },
  {
    icon: TrendingUp,
    name: "Investment scams",
    how: "Promises of guaranteed or very high returns, often in crypto, with pressure to join quickly.",
    signs: ["“Guaranteed” returns", "Limited spots or a countdown", "Payment by crypto, gift card or wire"],
    example: "Guaranteed 20% monthly returns. Only 5 spots left tonight.",
    protect: ["No real investment guarantees high returns", "Check any adviser with your bank or regulator first"],
    already: "Stop paying, keep every message and receipt, call your bank and report it at ReportFraud.ftc.gov.",
  },
  {
    icon: Briefcase,
    name: "Job scams",
    how: "An unexpected job offer with high pay for easy tasks, which later asks you to pay for training or equipment.",
    signs: ["An offer you didn’t apply for", "Pay for simple online tasks", "You have to pay before you earn"],
    example: "Remote job: earn $400 a day liking videos. Message us to start.",
    protect: ["Real employers don’t charge you to start", "Look the company up yourself, not through the message"],
    already: "Stop sending money, don’t share ID documents, and report the profile to the job site.",
  },
  {
    icon: Users,
    name: "Family emergency",
    how: "Someone pretends to be a relative in trouble (“new number, lost my phone”) and asks for money fast.",
    signs: ["A new number claiming to be family", "An urgent request for money", "Asking you not to tell anyone"],
    example: "Hi Mum, I lost my phone, this is my new number. Can you send $300 for rent today?",
    protect: ["Call the person on the number you already have", "Agree a family code word for emergencies"],
    already: "Call your bank right away to try to stop the payment, and report it.",
  },
];

export function SafetyCenterPage() {
  return (
    <Shell>
      <div className="cx-page-head">
        <p className="cx-eyebrow">Safety center</p>
        <h1>Spot the scam before it reaches you</h1>
        <p className="cx-muted">
          The most common scams, in plain words: how they work, the warning signs, how to protect yourself, and what to do
          if you already fell for one. No blame: these scams are built to fool careful people.
        </p>
      </div>
      <div className="cx-grid">
        {TOPICS.map(({ icon: Icon, name, how, signs, example, protect, already }) => (
          <article key={name} className="cx-card sx-panel">
            <div className="cx-row-top">
              <Icon size={16} aria-hidden="true" />
              <strong>{name}</strong>
            </div>
            <p>{how}</p>
            <div>
              <span className="cx-eyebrow">Warning signs</span>
              <ul className="sx-list">
                {signs.map((s) => (
                  <li key={s}>
                    <CircleAlert size={13} aria-hidden="true" /> {s}
                  </li>
                ))}
              </ul>
            </div>
            <p className="cx-mono cx-example">{example}</p>
            <div>
              <span className="cx-eyebrow">Protect yourself</span>
              <ul className="sx-list">
                {protect.map((s) => (
                  <li key={s}>
                    <BookOpen size={13} aria-hidden="true" /> {s}
                  </li>
                ))}
              </ul>
            </div>
            <p className="cx-small">
              <strong>Already fell for it?</strong> {already}
            </p>
          </article>
        ))}
      </div>
    </Shell>
  );
}
