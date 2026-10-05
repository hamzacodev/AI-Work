"use client";

import { useEffect, useState } from "react";
import { getScorecard } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Scorecard, ScorecardRun } from "@/lib/types";

const pct = (n: number | null) => (n === null ? "not measured" : `${n.toFixed(1)}%`);
const count = (n: number) => String(n);

const rows: { label: string; value: (r: ScorecardRun) => string }[] = [
  { label: "Deals closed", value: (r) => pct(r.closed_pct) },
  { label: "Limit broken", value: (r) => count(r.limit_breaks) },
  { label: "Private item shared", value: (r) => count(r.private_shared) },
  { label: "Invented facts", value: (r) => count(r.invented_facts) },
  { label: "Tricks blocked", value: (r) => pct(r.tricks_blocked_pct) },
  { label: "Average savings", value: (r) => pct(r.avg_savings_pct) },
  { label: "Research accuracy", value: (r) => pct(r.research_accuracy_pct) },
];

function latest(sc: Scorecard | null, mode: ScorecardRun["mode"]): ScorecardRun | null {
  const runs = (sc?.runs ?? []).filter((r) => r.mode === mode);
  runs.sort((a, b) => b.ran_at.localeCompare(a.ran_at));
  return runs[0] ?? null;
}

const CRITERIA: Record<string, string> = {
  accuracy: "Accuracy",
  output_quality: "Output quality",
  tool_usage: "Tool usage",
  routing: "Decision and routing",
  instruction_following: "Instruction following",
  efficiency: "Efficiency",
};

function Column({ title, run }: { title: string; run: ScorecardRun | null }) {
  const rb = run?.rubric ?? null;
  return (
    <section className="rounded-lg border border-border bg-surface p-4" aria-label={title}>
      <h2 className="text-lg font-medium text-text-primary">{title}</h2>
      {run ? (
        <>
          {rb && (
            <p className="mt-2 text-sm">
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${rb.passed ? "bg-accent-800 text-accent-50" : "bg-danger-100 text-danger-900"}`}>
                {rb.passed ? "Pass" : "Fail"}
              </span>{" "}
              <span className="text-text-primary">Rubric score {(rb.overall * 100).toFixed(0)} of 100</span>
              <span className="text-text-secondary"> (pass at {(rb.pass_score * 100).toFixed(0)}, and no hard failure)</span>
              {rb.hard_failures.length > 0 && <span className="block text-xs text-danger-text">Hard failures: {rb.hard_failures.join(", ")}</span>}
            </p>
          )}
          <dl className="mt-3 divide-y divide-border">
            {rows.map((r) => (
              <div key={r.label} className="flex justify-between py-2 text-sm">
                <dt className="text-text-secondary">{r.label}</dt>
                <dd className="font-medium text-text-primary">{r.value(run)}</dd>
              </div>
            ))}
          </dl>
          {rb && (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-text-secondary">Rubric by criterion</summary>
              <ul className="mt-2 space-y-1">
                {Object.entries(rb.criteria).map(([k, v]) => (
                  <li key={k} className="flex justify-between">
                    <span className="text-text-secondary">{CRITERIA[k] ?? k} ({rb.weights[k]}%)</span>
                    <span className="text-text-primary">{(v * 100).toFixed(0)} of 100</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {run.attack_suite && run.attack_suite.failures.length > 0 && (
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer text-text-secondary">Attacks that were not handled ({run.attack_suite.failures.length} of {run.attack_suite.n})</summary>
              <ul className="mt-2 space-y-1 text-xs text-text-secondary">
                {run.attack_suite.failures.slice(0, 12).map((f, i) => (
                  <li key={i}>&ldquo;{f.text}&rdquo; ({f.detail})</li>
                ))}
              </ul>
            </details>
          )}
          {run.detail?.judge && run.detail.judge.n_graded > 0 && (
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer text-text-secondary">
                Chat tone graded by the judge ({run.detail.judge.n_graded} chats, {((run.detail.judge.mean ?? 0) * 100).toFixed(0)} of 100)
              </summary>
              <ul className="mt-2 space-y-1">
                {Object.entries(run.detail.judge.criteria).map(([k, v]) => (
                  <li key={k} className="flex justify-between">
                    <span className="capitalize text-text-secondary">{k}</span>
                    <span className="text-text-primary">{(v * 100).toFixed(0)} of 100</span>
                  </li>
                ))}
              </ul>
              {run.detail.judge.worst.length > 0 && (
                <p className="mt-2 text-xs text-text-secondary">Lowest graded: {run.detail.judge.worst.map((w) => `${w.chat} (${w.note})`).join("; ")}</p>
              )}
            </details>
          )}
          <div className="mt-3 space-y-0.5 text-xs text-text-secondary">
            <p>Model: {run.model}</p>
            <p>Judge: {run.judge_model}. {run.judge_note}</p>
            <p>{run.n_deals} deals, run on {formatDate(run.ran_at)}</p>
            {run.detail?.tokens_per_deal != null && <p>About {run.detail.calls_per_deal} model calls and {run.detail.tokens_per_deal?.toLocaleString()} tokens per deal</p>}
          </div>
        </>
      ) : (
        <p className="mt-3 text-text-secondary">No run yet</p>
      )}
    </section>
  );
}

export default function ScorecardView() {
  const [sc, setSc] = useState<Scorecard | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getScorecard().then((r) => {
      setSc(r.data);
      setLoaded(true);
    });
  }, []);

  if (!loaded) return <p role="status" className="text-text-secondary">Loading the scorecard. If the server was asleep, this can take up to 30 seconds.</p>;
  if (!sc) {
    return (
      <div role="alert" className="space-y-2 rounded-2xl border border-border bg-surface shadow-card p-4">
        <p className="text-text-primary">The scorecard could not be loaded. The server did not answer.</p>
        <button
          type="button"
          className="rounded-md border border-border px-3 py-1.5 text-sm text-text-primary hover:bg-surface-2"
          onClick={() => {
            setLoaded(false);
            getScorecard().then((r) => {
              setSc(r.data);
              setLoaded(true);
            });
          }}
        >
          Try again
        </button>
      </div>
    );
  }

  const off = latest(sc, "safety_off");
  const on = latest(sc, "safety_on");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">Scorecard</h1>
        <p className="mt-1 text-text-secondary">
          Results from tests with fake vendors, with the safety checks off and on. Numbers come only from stored runs.
        </p>
      </div>
      {!off && !on && (
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-secondary">
          No run yet. Results appear here after an evaluation run is stored.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <Column title="Safety off" run={off} />
        <Column title="Safety on" run={on} />
      </div>
    </div>
  );
}
