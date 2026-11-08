import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useData } from "../hooks";
import {
  ActionButton,
  CampaignCard,
  EmptyState,
  PageTitle,
  PrivacyChip,
} from "../components";
export default function Campaigns({ state = "default" }: { state?: string }) {
  const { data } = useData(() => api.getCampaigns());
  const [expanded, setExpanded] = useState(state === "detail");
  const navigate = useNavigate();
  return (
    <div className="screen-pad campaign-screen">
      <PageTitle
        eyebrow="The bigger picture"
        description="Scammers repeat themselves. Recognizing the pattern helps explain the text."
      >
        A pattern,
        <br />
        not just a text.
      </PageTitle>
      {state === "empty" ? (
        <EmptyState
          title="No patterns to show yet."
          description="We have not matched any messages to a campaign. A single text can still need a closer look."
        />
      ) : (
        data?.map((campaign) => (
          <div key={campaign.id}>
            <CampaignCard
              campaign={campaign}
              onOpen={() => setExpanded(!expanded)}
            />
            {expanded && (
              <div className="campaign-detail">
                <h2 className="section-heading">The shared pattern</h2>
                <div className="redacted-message">
                  {campaign.template
                    .split(/(<[^>]+>)/g)
                    .map((part, i) =>
                      part.startsWith("<") ? (
                        <PrivacyChip key={i} token={part} />
                      ) : (
                        part
                      ),
                    )}
                </div>
                <h2 className="section-heading">Supporting public guidance</h2>
                {campaign.reports.map((report) => (
                  <blockquote key={report.publisher}>
                    <p>{report.claim}</p>
                    <cite>
                      {report.publisher} · {report.date}
                    </cite>
                  </blockquote>
                ))}
                <p className="quiet-note left">
                  Public guidance is supporting evidence. We also checked the
                  bill and the message pattern.
                </p>
                <ActionButton
                  secondary
                  onClick={() => navigate("/result?scenario=billing")}
                >
                  See the bill check
                </ActionButton>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
