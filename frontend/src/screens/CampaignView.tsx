import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { getCampaigns, getInbox } from "../api";
import { useData } from "../hooks";
import { CampaignCard, EmptyState, PageTitle, PrivacyChip, excerpt } from "../components";
import { maskLinks } from "../present";
import type { Campaign, InboxItem } from "../types";

/** Placeholders such as <BRAND> or <URL> become soft chips. */
function RedactedText({ text }: { text: string }) {
  return (
    <div className="redacted-message">
      {text.split(/(<[^>]+>)/g).map((part, i) => (part.startsWith("<") ? <PrivacyChip key={i} token={part} /> : part))}
    </div>
  );
}

/** Campaign cards: count today, first seen, then the redacted template and linked messages on tap. */
export function CampaignListView({
  campaigns,
  inbox = [],
  expanded = [],
  error = false,
  onToggle,
  onOpenMessage,
  onRetry,
}: {
  campaigns?: Campaign[];
  inbox?: InboxItem[];
  expanded?: string[];
  error?: boolean;
  onToggle?: (campaignId: string) => void;
  onOpenMessage?: (messageId: string) => void;
  onRetry?: () => void;
}) {
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
      {error ? (
        <EmptyState
          error
          title="We couldn’t load the patterns."
          description="Nothing was changed. Each message is still checked on its own."
          onRetry={onRetry}
        />
      ) : campaigns && campaigns.length === 0 ? (
        <EmptyState
          title="No patterns to show yet."
          description="We have not matched any messages to a campaign. A single text can still need a closer look."
        />
      ) : (
        campaigns?.map((campaign) => (
          <div key={campaign.campaign_id}>
            <CampaignCard campaign={campaign} onOpen={() => onToggle?.(campaign.campaign_id)} />
            {expanded.includes(campaign.campaign_id) && (
              <div className="campaign-detail">
                <h2 className="section-heading">The shared pattern</h2>
                <RedactedText text={campaign.template} />
                <h2 className="section-heading">In your messages</h2>
                {campaign.linked_message_ids.map((messageId) => {
                  const item = inbox.find((row) => row.message_id === messageId);
                  return (
                    <button className="row-link" key={messageId} onClick={() => onOpenMessage?.(messageId)}>
                      {item ? excerpt(maskLinks(item.text), 48) : "A message in your inbox"}
                      <ChevronRight size={18} />
                    </button>
                  );
                })}
                <p className="quiet-note left">
                  Counts are anonymized. We keep pattern fingerprints, never message text.
                </p>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

export default function CampaignView() {
  const navigate = useNavigate();
  const [attempt, setAttempt] = useState(0);
  const { data, error } = useData(() => getCampaigns(), [attempt]);
  const { data: inbox } = useData(() => getInbox(), []);
  const [expanded, setExpanded] = useState<string[]>([]);
  return (
    <CampaignListView
      campaigns={data}
      inbox={inbox}
      expanded={expanded}
      error={error}
      onToggle={(id) => setExpanded((all) => (all.includes(id) ? all.filter((x) => x !== id) : [...all, id]))}
      onOpenMessage={(id) => navigate(`/result/${encodeURIComponent(id)}`)}
      onRetry={() => setAttempt((n) => n + 1)}
    />
  );
}
