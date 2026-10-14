import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiGet } from "../lib/api";
import { formatTime } from "../lib/format";
import type { TraceRun } from "../types";
import { Empty, ErrorView, Loading } from "../components/StateViews";

interface Point {
  label: string;
  time: string;
  latency_ms: number;
  tokens: number;
  errors: number;
  blocked: number;
}

export function MetricsPage() {
  const [runs, setRuns] = useState<TraceRun[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rate, setRate] = useState(0);

  function fetchRuns() {
    apiGet<{ runs: TraceRun[] }>("/traces?limit=50")
      .then((data) => setRuns(data.runs))
      .catch(setError);
  }

  function refresh() {
    setError(null);
    setRuns(null);
    fetchRuns();
  }

  useEffect(fetchRuns, []);

  const points: Point[] = useMemo(() => {
    if (!runs) return [];
    const chronological = [...runs].reverse();
    return chronological.map((r, i) => ({
      label: `#${i + 1}`,
      time: formatTime(r.created_at),
      latency_ms: r.latency_ms,
      tokens: r.tokens,
      errors: r.errors,
      blocked: r.status === "blocked" ? 1 : 0,
    }));
  }, [runs]);

  const totalTokens = points.reduce((sum, p) => sum + p.tokens, 0);
  const totalErrors = points.reduce((sum, p) => sum + p.errors, 0);
  const totalBlocked = points.reduce((sum, p) => sum + p.blocked, 0);
  const cost = (totalTokens / 1000) * rate;

  return (
    <div>
      <div className="page-header">
        <h2>Metrics</h2>
        <button className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>

      {error ? <ErrorView error={error} /> : null}
      {!error && runs === null ? <Loading /> : null}
      {!error && runs?.length === 0 ? (
        <Empty>No trace data yet. Metrics are derived from recent /chat runs.</Empty>
      ) : null}

      {points.length > 0 ? (
        <>
          <div className="stat-row">
            <div className="stat">
              <label>Total tokens</label>
              <span className="value">{totalTokens}</span>
            </div>
            <div className="stat">
              <label>Estimated cost</label>
              <span className="value">${cost.toFixed(4)}</span>
              <div>
                <label htmlFor="rate" className="muted">
                  $ per 1K tokens:{" "}
                </label>
                <input
                  id="rate"
                  type="number"
                  min={0}
                  step={0.001}
                  value={rate}
                  onChange={(e) => setRate(Number(e.target.value) || 0)}
                />
              </div>
            </div>
            <div className="stat">
              <label>Span errors</label>
              <span className="value">{totalErrors}</span>
            </div>
            <div className="stat">
              <label>Guardrail blocks</label>
              <span className="value">{totalBlocked}</span>
            </div>
          </div>

          <div className="grid">
            <div className="card chart-card">
              <h3>Latency over time</h3>
              <p className="muted">Milliseconds per run, oldest to newest</p>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={points}>
                  <CartesianGrid stroke="var(--gridline)" vertical={false} />
                  <XAxis dataKey="label" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
                  <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} width={40} />
                  <Tooltip content={<ChartTooltip unit="ms" dataKey="latency_ms" />} />
                  <Line
                    type="monotone"
                    dataKey="latency_ms"
                    stroke="var(--series-1)"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="card chart-card">
              <h3>Token usage over time</h3>
              <p className="muted">Tokens consumed per run</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={points}>
                  <CartesianGrid stroke="var(--gridline)" vertical={false} />
                  <XAxis dataKey="label" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
                  <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} width={40} />
                  <Tooltip content={<ChartTooltip unit="tok" dataKey="tokens" />} />
                  <Bar dataKey="tokens" fill="var(--series-2)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="card chart-card">
              <h3>Span errors over time</h3>
              <p className="muted">Error-recording spans per run</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={points}>
                  <CartesianGrid stroke="var(--gridline)" vertical={false} />
                  <XAxis dataKey="label" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
                  <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} width={40} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip unit="" dataKey="errors" />} />
                  <Bar dataKey="errors" fill="var(--critical)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="card chart-card">
              <h3>Guardrail blocks over time</h3>
              <p className="muted">1 = request blocked by prompt-injection guard</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={points}>
                  <CartesianGrid stroke="var(--gridline)" vertical={false} />
                  <XAxis dataKey="label" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
                  <YAxis
                    stroke="var(--text-muted)"
                    fontSize={12}
                    tickLine={false}
                    width={40}
                    allowDecimals={false}
                    domain={[0, 1]}
                  />
                  <Tooltip content={<ChartTooltip unit="" dataKey="blocked" />} />
                  <Bar dataKey="blocked" fill="var(--warning)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function ChartTooltip({
  active,
  payload,
  unit,
  dataKey,
}: {
  active?: boolean;
  payload?: Array<{ payload: Point }>;
  unit: string;
  dataKey: keyof Point;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="card" style={{ padding: "6px 10px", fontSize: 12 }}>
      <div className="muted">{point.time}</div>
      <div>
        {String(point[dataKey])} {unit}
      </div>
    </div>
  );
}
