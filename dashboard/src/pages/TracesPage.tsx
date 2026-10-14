import { useEffect, useState } from "react";
import { apiGet } from "../lib/api";
import { formatTime, truncate } from "../lib/format";
import type { TraceRun } from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { Empty, ErrorView, Loading } from "../components/StateViews";

export function TracesPage() {
  const [runs, setRuns] = useState<TraceRun[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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

  const selected = runs?.find((r) => r.run_id === selectedId) ?? null;

  return (
    <div>
      <div className="page-header">
        <h2>Traces</h2>
        <button className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>

      {error ? <ErrorView error={error} /> : null}
      {!error && runs === null ? <Loading /> : null}
      {!error && runs?.length === 0 ? (
        <Empty>No runs yet. Send a few requests to POST /chat first.</Empty>
      ) : null}

      {runs && runs.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Role</th>
                <th>Status</th>
                <th>Question</th>
                <th>Latency</th>
                <th>Tokens</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.run_id}
                  className={`clickable ${r.run_id === selectedId ? "selected" : ""}`}
                  onClick={() => setSelectedId(r.run_id === selectedId ? null : r.run_id)}
                >
                  <td>{formatTime(r.created_at)}</td>
                  <td>{r.role}</td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="wrap">{truncate(r.question, 60)}</td>
                  <td>{r.latency_ms.toFixed(1)} ms</td>
                  <td>{r.tokens}</td>
                  <td>{r.errors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {selected ? (
        <div className="panel card">
          <h3>Spans for {selected.run_id}</h3>
          <p className="muted">{selected.question}</p>
          <SpanTimeline spans={selected.spans} />
          <p className="muted" style={{ marginTop: 12 }}>
            Answer: {selected.answer || "(none yet)"}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function SpanTimeline({ spans }: { spans: TraceRun["spans"] }) {
  if (spans.length === 0) return <Empty>No spans recorded for this run.</Empty>;
  const max = Math.max(...spans.map((s) => s.latency_ms), 1);
  return (
    <div style={{ marginTop: 12 }}>
      {spans.map((s, i) => (
        <div className="span-row" key={`${s.name}-${i}`}>
          <span>{s.name}</span>
          <div className="span-bar-track">
            <div
              className={`span-bar-fill ${s.error ? "has-error" : ""}`}
              style={{ width: `${Math.max((s.latency_ms / max) * 100, 2)}%` }}
              title={s.error ?? undefined}
            />
          </div>
          <span className="muted">{s.latency_ms.toFixed(2)} ms</span>
          <span className="muted">{s.tokens} tok</span>
        </div>
      ))}
    </div>
  );
}
