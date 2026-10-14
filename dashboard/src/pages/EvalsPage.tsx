import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiGet } from "../lib/api";
import { formatTime } from "../lib/format";
import type { EvalHistoryEntry } from "../types";
import { Empty, ErrorView, Loading } from "../components/StateViews";

export function EvalsPage() {
  const [history, setHistory] = useState<EvalHistoryEntry[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  function fetchHistory() {
    apiGet<{ history: EvalHistoryEntry[] }>("/evals")
      .then((data) => setHistory(data.history))
      .catch(setError);
  }

  function refresh() {
    setError(null);
    setHistory(null);
    fetchHistory();
  }

  useEffect(fetchHistory, []);

  // history.json is append-only, so the API returns it oldest-first already --
  // that's the order the chart wants. The table shows newest-first instead.
  const chartData = (history ?? []).map((e, i) => ({
    label: `#${i + 1}`,
    time: formatTime(e.timestamp),
    groundedness: e.metrics.groundedness,
    tool_accuracy: e.metrics.tool_accuracy,
    correctness: e.metrics.correctness,
    pass_rate: e.metrics.pass_rate,
  }));

  return (
    <div>
      <div className="page-header">
        <h2>Evals</h2>
        <button className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>

      {error ? <ErrorView error={error} /> : null}
      {!error && history === null ? <Loading /> : null}
      {!error && history?.length === 0 ? (
        <Empty>No eval runs recorded yet. Run `python -m evals.run_evals` to add one.</Empty>
      ) : null}

      {history && history.length > 0 ? (
        <>
          <div className="card chart-card" style={{ marginBottom: 16 }}>
            <h3>Quality metrics over time</h3>
            <p className="muted">0–1 scores, each run of evals/run_evals.py</p>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData}>
                <CartesianGrid stroke="var(--gridline)" vertical={false} />
                <XAxis dataKey="label" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
                <YAxis
                  stroke="var(--text-muted)"
                  fontSize={12}
                  tickLine={false}
                  width={40}
                  domain={[0, 1]}
                />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="pass_rate" name="Pass rate" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="groundedness" name="Groundedness" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="tool_accuracy" name="Tool accuracy" stroke="var(--series-3)" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="correctness" name="Correctness" stroke="var(--series-4)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Pass rate</th>
                  <th>Groundedness</th>
                  <th>Tool accuracy</th>
                  <th>Correctness</th>
                  <th>p95 latency</th>
                  <th>Avg tokens</th>
                  <th>Regression</th>
                </tr>
              </thead>
              <tbody>
                {[...history].reverse().map((e, i) => (
                  <tr key={i} className={e.regressed ? "regressed" : ""}>
                    <td>{formatTime(e.timestamp)}</td>
                    <td>{e.metrics.pass_rate}</td>
                    <td>{e.metrics.groundedness}</td>
                    <td>{e.metrics.tool_accuracy}</td>
                    <td>{e.metrics.correctness}</td>
                    <td>{e.metrics.p95_latency_ms} ms</td>
                    <td>{e.metrics.avg_tokens}</td>
                    <td>{e.regressed ? <span className="badge badge-critical">⚠ Regressed</span> : <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
