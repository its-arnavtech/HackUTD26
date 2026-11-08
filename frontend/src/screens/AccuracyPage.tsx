import { useState, type ReactNode } from "react";
import { ArrowDownRight, Beaker, ChevronRight } from "lucide-react";
import { getMetrics, type Failure } from "../api";
import { useData, useHealth } from "../hooks";
import { MetricTable } from "../components";
import type { Metrics, OursVsBaseline } from "../types";

type Dataset = "synthetic" | "public";

/** Judge-facing only: the one place percentages are allowed. */
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

const same = (pair: OursVsBaseline) => Math.abs(pair.ours - pair.baseline) < 1e-9;

/** True when every score matches the baseline, as it does until L7's classifier replaces the stand-in. */
export function oursMatchesBaseline(metrics: Metrics): boolean {
  return (
    same(metrics.macro_f1) &&
    same(metrics.false_positive_rate) &&
    metrics.categories.every((row) =>
      (["precision", "recall", "f1"] as const).every((k) => same({ ours: row.ours[k], baseline: row.baseline[k] })),
    )
  );
}

const measuredOn = (value: string) =>
  new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
  }).format(new Date(value));

function Pair({
  eyebrow,
  before,
  after,
  beforeLabel,
  afterLabel,
  down = false,
  children,
}: {
  eyebrow: string;
  before?: string;
  after?: string;
  beforeLabel: string;
  afterLabel: string;
  down?: boolean;
  children: ReactNode;
}) {
  return (
    <article>
      <p className="eyebrow">{eyebrow}</p>
      <div className="metric-pair">
        <span>
          {before ?? "—"}
          <small>{beforeLabel}</small>
        </span>
        {down ? <ArrowDownRight size={30} /> : <ChevronRight size={26} />}
        <strong>
          {after ?? "—"}
          <small>{afterLabel}</small>
        </strong>
      </div>
      <p>{children}</p>
    </article>
  );
}

/** The public SMS set has no categories: one row of spam recall and false positive rate. */
function PublicSetTable({ metrics }: { metrics: NonNullable<Metrics["public_set"]> }) {
  return (
    <div className="table-scroll">
      <table className="metric-table">
        <caption>Real public SMS messages. Used for evaluation only, never for training.</caption>
        <thead>
          <tr>
            <th rowSpan={2}>Messages</th>
            <th rowSpan={2}>Samples</th>
            <th colSpan={2}>Simple baseline</th>
            <th colSpan={2} className="our-column">
              SentinelAI
            </th>
          </tr>
          <tr>
            {["Spam recall", "False positives", "Spam recall", "False positives"].map((x, i) => (
              <th key={i} className={i >= 2 ? "our-column" : ""}>
                {x}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">All messages</th>
            <td>{metrics.n}</td>
            <td>{pct(metrics.spam_recall.baseline)}</td>
            <td>{pct(metrics.false_positive_rate.baseline)}</td>
            <td className="our-column">{pct(metrics.spam_recall.ours)}</td>
            <td className="our-column">{pct(metrics.false_positive_rate.ours)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/** Reads the `eval/metrics.json` shape (DATA_SPEC 7). `illustrative` marks the gallery's mock file. */
export function AccuracyView({
  metrics,
  illustrative = false,
  error = false,
  failure,
  onRetry,
}: {
  metrics?: Metrics;
  illustrative?: boolean;
  error?: boolean;
  failure?: Failure;
  onRetry?: () => void;
}) {
  const [dataset, setDataset] = useState<Dataset>("synthetic");
  const publicSet = metrics?.public_set ?? undefined;
  const showing: Dataset = dataset === "public" && publicSet ? "public" : "synthetic";
  const fpr = showing === "public" ? publicSet?.false_positive_rate : metrics?.false_positive_rate;
  const agent = metrics?.agent_sample;
  return (
    <main className="accuracy-page">
      <div className="accuracy-heading">
        <div>
          <p className="eyebrow">For the judges · Evaluation workspace</p>
          <h1>
            Trust should
            <br />
            be measurable.
          </h1>
        </div>
        <p>
          Detection matters.
          <br />
          So do the messages we leave alone.
        </p>
      </div>
      <div className="fixture-banner">
        <Beaker size={22} />
        <div>
          {error ? (
            <>
              <strong>
                {failure === "not_wired"
                  ? "The live evaluation route isn’t connected yet."
                  : failure === "offline"
                    ? "The API couldn’t be reached."
                    : "The evaluation results couldn’t be loaded."}
              </strong>
              <p>No numbers are shown rather than guessed. Run the evaluation and try again.</p>
              {onRetry && (
                <button className="text-button" onClick={onRetry}>
                  Try again
                </button>
              )}
            </>
          ) : illustrative ? (
            <>
              <strong>Illustrative data. Not measured model performance.</strong>
              <p>These numbers come from the mock file. With the metrics route live, this page reads eval/metrics.json.</p>
            </>
          ) : metrics && oursMatchesBaseline(metrics) ? (
            <>
              <strong>SentinelAI’s classifier is still the baseline stand-in.</strong>
              <p>
                Both columns come from the same model until the improved classifier is evaluated. Measured{" "}
                {measuredOn(metrics.generated_at)}.
              </p>
            </>
          ) : metrics ? (
            <>
              <strong>Measured on the held-out test split.</strong>
              <p>Results generated {measuredOn(metrics.generated_at)}.</p>
            </>
          ) : (
            <>
              <strong>Loading the evaluation…</strong>
              <p>Reading the latest results.</p>
            </>
          )}
        </div>
      </div>
      <div className="accuracy-controls">
        <div className="segmented" aria-label="Evaluation dataset">
          {(["synthetic", "public"] as const).map((value) => (
            <button
              key={value}
              aria-pressed={showing === value}
              disabled={value === "public" && !publicSet}
              onClick={() => setDataset(value)}
            >
              {value === "synthetic" ? "Held-out synthetic" : "Public SMS"}
            </button>
          ))}
        </div>
        {metrics && (
          <p>
            {showing === "public" && publicSet ? `${publicSet.n} messages` : `${metrics.n_test} messages`} · Test split
            only
          </p>
        )}
      </div>
      <div className="metric-cards">
        <Pair
          eyebrow="False positive rate"
          before={fpr && pct(fpr.baseline)}
          after={fpr && pct(fpr.ours)}
          beforeLabel="Baseline"
          afterLabel="SentinelAI"
          down
        >
          Legitimate messages flagged as scams.
          <br />
          Lower is better.
        </Pair>
        {showing === "public" && publicSet ? (
          <Pair
            eyebrow="Spam recall"
            before={pct(publicSet.spam_recall.baseline)}
            after={pct(publicSet.spam_recall.ours)}
            beforeLabel="Baseline"
            afterLabel="SentinelAI"
          >
            Spam messages we caught.
            <br />
            Higher is better.
          </Pair>
        ) : (
          <Pair
            eyebrow="Cost of redaction · Macro F1"
            before={metrics?.redaction_cost?.macro_f1_unredacted.toFixed(2)}
            after={metrics?.redaction_cost?.macro_f1_redacted.toFixed(2)}
            beforeLabel="Before redaction"
            afterLabel="After redaction"
          >
            The same classifier and test set,
            <br />
            with personal details removed.
          </Pair>
        )}
        <article className="method-card">
          <p className="eyebrow">How to read this</p>
          <h2>
            More than
            <br />
            one score.
          </h2>
          <p>
            Precision: how often a flag is right.
            <br />
            Recall: how many scams we catch.
            <br />
            F1: the balance between both.
          </p>
        </article>
      </div>
      <div className="table-heading">
        <h2>{showing === "public" ? "Real messages, too." : "Every category counts."}</h2>
        <span>
          {showing === "public" && publicSet
            ? publicSet.dataset
            : metrics
              ? `Macro F1 · baseline ${metrics.macro_f1.baseline.toFixed(2)} · SentinelAI ${metrics.macro_f1.ours.toFixed(2)}`
              : ""}
        </span>
      </div>
      {metrics &&
        (showing === "public" && publicSet ? (
          <PublicSetTable metrics={publicSet} />
        ) : (
          <MetricTable rows={metrics.categories} />
        ))}
      <div className="accuracy-method">
        <p>
          <strong>A fair comparison.</strong> Both models use the same held-out split. Test messages never train the
          model, seed campaigns, or shape prompts.
        </p>
        <p>
          <strong>An honest boundary.</strong> Classifier scores are separate from the full agent verdict.{" "}
          {agent
            ? `On a sample of ${agent.n} messages run through the full agent, ${pct(agent.share_correct)} were correct and ${pct(agent.share_unsure)} came back “not sure.”`
            : "The full-agent sample hasn’t been run yet, so agent accuracy and the share returned as “not sure” aren’t shown."}
        </p>
        {showing === "public" && publicSet && publicSet.spam_recall.ours < publicSet.spam_recall.baseline && (
          <p>
            <strong>Where it falls short.</strong> On real public messages, SentinelAI catches fewer spam texts than the
            simple baseline ({pct(publicSet.spam_recall.ours)} vs {pct(publicSet.spam_recall.baseline)}). The classifier
            is one signal; the agent still checks the facts with its tools before it answers.
          </p>
        )}
      </div>
      <footer className="accuracy-footer">
        SentinelAI · HackUTD 2026 <span>Synthetic test data · No live customer data</span>
      </footer>
    </main>
  );
}

export default function AccuracyPage() {
  const { data, failure, retry } = useData(() => getMetrics(), []);
  // While /api/metrics serves its mock (USE_MOCKS or MOCK_ROUTES), label the numbers illustrative.
  const mocked = useHealth()?.mocked_routes.metrics === true;
  return <AccuracyView metrics={data} illustrative={mocked} error={failure !== undefined} failure={failure} onRetry={retry} />;
}
