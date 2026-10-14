import { useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { ApprovalResult, PendingApproval } from "../types";
import { Empty, ErrorView, Loading } from "../components/StateViews";

export function ApprovalsPage() {
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [resolutions, setResolutions] = useState<Record<string, ApprovalResult>>({});

  function fetchPending() {
    apiGet<{ pending: PendingApproval[] }>("/approvals")
      .then((data) => setPending(data.pending))
      .catch(setError);
  }

  function refresh() {
    setError(null);
    setPending(null);
    fetchPending();
  }

  useEffect(fetchPending, []);

  async function resolve(runId: string, decision: "approve" | "reject") {
    setBusyId(runId);
    setActionErrors((prev) => ({ ...prev, [runId]: "" }));
    try {
      const result = await apiPost<ApprovalResult>(`/approvals/${runId}`, { decision });
      setResolutions((prev) => ({ ...prev, [runId]: result }));
      setPending((prev) => prev?.filter((p) => p.run_id !== runId) ?? prev);
    } catch (e) {
      const message = e instanceof ApiError ? e.message : String(e);
      setActionErrors((prev) => ({ ...prev, [runId]: message }));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2>Approvals</h2>
        <button className="btn" onClick={refresh}>
          Refresh
        </button>
      </div>

      {error ? <ErrorView error={error} /> : null}
      {!error && pending === null ? <Loading /> : null}
      {!error && pending?.length === 0 ? <Empty>No pending approvals.</Empty> : null}

      {pending && pending.length > 0 ? (
        <div className="table-wrap">
          {pending.map((p) => (
            <div className="approval-card" key={p.run_id}>
              <div>
                <strong>{p.tool}</strong>{" "}
                <span className="muted">
                  ({Object.entries(p.args).map(([k, v]) => `${k}=${v}`).join(", ")})
                </span>
                <div className="muted">
                  {p.question} — requested by {p.role}
                </div>
                {actionErrors[p.run_id] ? (
                  <div className="muted" style={{ color: "var(--critical)" }}>
                    {actionErrors[p.run_id]}
                  </div>
                ) : null}
              </div>
              <div className="approval-actions">
                <button
                  className="btn btn-primary"
                  disabled={busyId === p.run_id}
                  onClick={() => resolve(p.run_id, "approve")}
                >
                  Approve
                </button>
                <button
                  className="btn btn-danger"
                  disabled={busyId === p.run_id}
                  onClick={() => resolve(p.run_id, "reject")}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {Object.keys(resolutions).length > 0 ? (
        <div className="panel">
          <h3>Recently resolved</h3>
          {Object.entries(resolutions)
            .reverse()
            .map(([runId, result]) => (
              <div className="resolution" key={runId}>
                <strong>{result.tool_results[0]?.status === "ran" ? "Approved" : "Rejected"}</strong>{" "}
                <span className="muted">{runId}</span> — {result.answer}
              </div>
            ))}
        </div>
      ) : null}
    </div>
  );
}
