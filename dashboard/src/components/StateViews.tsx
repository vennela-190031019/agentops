import type { ReactNode } from "react";
import { ApiError } from "../lib/api";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="state state-loading">{label}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state state-empty">{children}</p>;
}

export function ErrorView({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return (
        <div className="state state-error">
          <strong>401 Unauthorized.</strong> The API key is missing or invalid. Check{" "}
          <code>VITE_API_KEY</code> in <code>dashboard/.env.local</code> against the API's{" "}
          <code>AGENTOPS_API_KEYS</code>.
        </div>
      );
    }
    if (error.status === 403) {
      return (
        <div className="state state-error">
          <strong>403 Forbidden.</strong> This API key's role isn't allowed to view this page. The
          Approvals page (and this one, if you're seeing this there) needs a key mapped to the{" "}
          <code>reviewer</code> role.
        </div>
      );
    }
    return (
      <div className="state state-error">
        <strong>Request failed ({error.status || "network"}).</strong> {error.message}
      </div>
    );
  }
  return <div className="state state-error">Something went wrong. {String(error)}</div>;
}
