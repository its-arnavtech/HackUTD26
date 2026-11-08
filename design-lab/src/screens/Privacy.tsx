import { Eye, EyeOff, Fingerprint, LockKeyhole } from "lucide-react";
import { api } from "../api";
import { useData } from "../hooks";
import { PageTitle, PrivacyChip } from "../components";
import type { ScenarioId } from "../types";
export default function Privacy({
  scenario = "bank",
}: {
  scenario?: ScenarioId;
}) {
  const { data } = useData(() => api.getPrivacy(scenario), [scenario]);
  return (
    <div className="screen-pad privacy-screen">
      <PageTitle eyebrow="Private before intelligent">
        What we checked.
        <br />
        What we never saw.
      </PageTitle>
      <div className="privacy-banner">
        <LockKeyhole size={23} />
        <p>
          Personal details are hidden before the classifier or AI sees a
          message.
        </p>
      </div>
      <h2 className="section-heading">The message after redaction</h2>
      <div className="redacted-message">
        {data?.text_redacted
          .split(/(<[^>]+>)/g)
          .map((part, i) =>
            part.startsWith("<") ? <PrivacyChip key={i} token={part} /> : part,
          )}
      </div>
      <div className="redaction-counts">
        {data &&
          Object.entries(data.redaction.counts)
            .filter(([, value]) => value > 0)
            .map(([key, value]) => (
              <span key={key}>
                {value}{" "}
                {key === "PERSON"
                  ? "name"
                  : key === "PHONE"
                    ? "personal number"
                    : "account digits"}{" "}
                hidden
              </span>
            ))}
      </div>
      <p className="quiet-note left">
        Kept for the check: {data?.redaction.kept.join(", ")}.
      </p>
      {data?.recipients.map((recipient) => (
        <section className="privacy-recipient" key={recipient.name}>
          <h2>{recipient.name}</h2>
          <div className="boundary-label">
            <Eye size={17} />
            What was received
          </div>
          <ul>
            {recipient.received.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <div className="boundary-label">
            <EyeOff size={17} />
            What was never received
          </div>
          <ul>
            {recipient.never.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </section>
      ))}
      <section className="storage-note">
        <Fingerprint size={25} />
        <h2>What stays?</h2>
        <p>
          Only {data?.stored[0].toLowerCase()} is stored. Message text and bank
          records stay in memory for this session only.
        </p>
      </section>
    </div>
  );
}
