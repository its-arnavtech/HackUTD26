import { useParams } from "react-router-dom";
import { Eye, EyeOff, Fingerprint, LockKeyhole } from "lucide-react";
import { getPrivacy } from "../api";
import { useData } from "../hooks";
import { PageTitle, PrivacyChip } from "../components";
import { claimedBrand, receivedLines, recipientLabel, redactedText, redactionCounts } from "../present";
import type { PrivacyView as PrivacyData } from "../types";

/** What was hidden, what each check received, and what never left the phone. */
export function PrivacyView({ view }: { view?: PrivacyData }) {
  const text = view ? redactedText(view) : undefined;
  const brand = view ? claimedBrand(view) : undefined;
  return (
    <div className="screen-pad privacy-screen">
      <PageTitle eyebrow="Private before intelligent">
        What we checked.
        <br />
        What we never saw.
      </PageTitle>
      <div className="privacy-banner">
        <LockKeyhole size={23} />
        <p>Personal details are hidden before the classifier or AI sees a message.</p>
      </div>
      {!view ? (
        <div className="loading-screen" role="status">
          Loading what we checked…
        </div>
      ) : (
        <>
          <h2 className="section-heading">The message after redaction</h2>
          {text ? (
            <div className="redacted-message">
              {brand && <p className="eyebrow">Text claiming to be {brand}</p>}
              {text.split(/(<[A-Z][A-Z0-9_]*>)/g).map((part, i) =>
                /^<[A-Z][A-Z0-9_]*>$/.test(part) ? <PrivacyChip key={i} token={part} /> : part,
              )}
            </div>
          ) : (
            <p className="quiet-note left">This check has no redacted message to show.</p>
          )}
          <div className="redaction-counts">
            {redactionCounts(view.redaction.counts).map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
          {view.redaction.kept.length > 0 && (
            <p className="quiet-note left">Kept for the check: {view.redaction.kept.join(", ")}.</p>
          )}
          {view.recipients.map((recipient) => (
            <section className="privacy-recipient" key={`${recipient.recipient}-${recipient.at ?? ""}`}>
              <h2>{recipientLabel(recipient)}</h2>
              <div className="boundary-label">
                <Eye size={17} />
                What was received
              </div>
              <ul>
                {receivedLines(recipient).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>
          ))}
          <section className="privacy-recipient">
            <h2>What we never saw</h2>
            <div className="boundary-label">
              <EyeOff size={17} />
              Never sent to a model or a tool
            </div>
            <ul>
              {view.never_sent.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
          <section className="storage-note">
            <Fingerprint size={25} />
            <h2>What stays?</h2>
            <p>Only anonymized campaign fingerprints are stored. Message text and bank records stay in memory for this session only.</p>
          </section>
        </>
      )}
    </div>
  );
}

export default function PrivacyPanel() {
  const { messageId = "msg_0001" } = useParams();
  const { data, error } = useData(() => getPrivacy(messageId), [messageId]);
  if (error) {
    return (
      <div className="screen-pad privacy-screen">
        <PageTitle eyebrow="Private before intelligent" description="We couldn’t load this check. Nothing extra was sent.">
          What we checked.
          <br />
          What we never saw.
        </PageTitle>
      </div>
    );
  }
  return <PrivacyView view={data} />;
}
