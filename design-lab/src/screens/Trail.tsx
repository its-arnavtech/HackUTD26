import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useData } from "../hooks";
import { ActionButton, PageTitle, TrailStep } from "../components";
import type { ResultState, ScenarioId } from "../types";
export default function Trail({
  scenario = "bank",
  animate = true,
  state = "scam",
}: {
  scenario?: ScenarioId;
  animate?: boolean;
  state?: ResultState;
}) {
  const { data } = useData(
    () => api.getScenario(scenario, state),
    [scenario, state],
  );
  const navigate = useNavigate();
  return (
    <div className="screen-pad trail-screen">
      <PageTitle
        eyebrow="The reasoning, made visible"
        description="Each check has a purpose. Here’s what we found and why we looked."
      >
        How we
        <br />
        checked.
      </PageTitle>
      <div className="agent-label">
        <span className="status-dot" />
        Planned by Nemotron · Details hidden first
      </div>
      <div className="trail-list">
        {data?.trail.map((entry, index) => (
          <TrailStep
            entry={entry}
            index={index}
            key={entry.step}
            animate={animate}
          />
        ))}
      </div>
      <ActionButton
        secondary
        onClick={() => navigate(`/result?scenario=${scenario}&state=${state}`)}
      >
        Back to your result
      </ActionButton>
    </div>
  );
}
