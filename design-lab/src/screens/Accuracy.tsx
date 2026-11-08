import { useState } from "react";
import { ArrowDownRight, Beaker, ChevronRight } from "lucide-react";
import { api } from "../api";
import { useData } from "../hooks";
import { MetricTable } from "../components";
export default function Accuracy() {
  const [dataset, setDataset] = useState<"synthetic" | "public">("synthetic");
  const { data } = useData(() => api.getMetrics(dataset), [dataset]);
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
          <strong>Illustrative data. Not measured model performance.</strong>
          <p>
            These fixtures demonstrate the evaluation layout. Replace them with
            eval/metrics.json before judging.
          </p>
        </div>
      </div>
      <div className="accuracy-controls">
        <div className="segmented" aria-label="Evaluation dataset">
          {(["synthetic", "public"] as const).map((value) => (
            <button
              key={value}
              aria-pressed={dataset === value}
              onClick={() => setDataset(value)}
            >
              {value === "synthetic" ? "Held-out synthetic" : "Public SMS"}
            </button>
          ))}
        </div>
        <p>{data?.sample_size} fixture samples · Test split only</p>
      </div>
      <div className="metric-cards">
        <article>
          <p className="eyebrow">False positive rate</p>
          <div className="metric-pair">
            <span>
              {data ? `${data.false_positive_rate.baseline * 100}%` : "—"}
              <small>Baseline</small>
            </span>
            <ArrowDownRight size={30} />
            <strong>
              {data ? `${data.false_positive_rate.sentinel * 100}%` : "—"}
              <small>SentinelAI</small>
            </strong>
          </div>
          <p>
            Legitimate messages flagged as scams.
            <br />
            Lower is better.
          </p>
        </article>
        <article>
          <p className="eyebrow">Cost of redaction · Macro F1</p>
          <div className="metric-pair">
            <span>
              {data?.redaction.before.toFixed(2)}
              <small>Before redaction</small>
            </span>
            <ChevronRight size={26} />
            <strong>
              {data?.redaction.after.toFixed(2)}
              <small>After redaction</small>
            </strong>
          </div>
          <p>
            The same classifier and test set,
            <br />
            with personal details removed.
          </p>
        </article>
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
        <h2>Every category counts.</h2>
        <span>{data?.dataset}</span>
      </div>
      {data && <MetricTable rows={data.rows} />}
      <div className="accuracy-method">
        <p>
          <strong>A fair comparison.</strong> Both models use the same held-out
          split. Test messages never train the model, seed campaigns, or shape
          prompts.
        </p>
        <p>
          <strong>An honest boundary.</strong> Classifier scores are separate
          from the full agent verdict. Production reporting also needs agent
          accuracy and the share returned as “not sure.”
        </p>
      </div>
      <footer className="accuracy-footer">
        SentinelAI · HackUTD 2026{" "}
        <span>Authored fixtures · No live customer data</span>
      </footer>
    </main>
  );
}
