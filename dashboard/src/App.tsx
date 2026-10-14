import { useState } from "react";
import "./App.css";
import { TracesPage } from "./pages/TracesPage";
import { MetricsPage } from "./pages/MetricsPage";
import { EvalsPage } from "./pages/EvalsPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";

const PAGES = ["Traces", "Metrics", "Evals", "Approvals"] as const;
type Page = (typeof PAGES)[number];

function App() {
  const [page, setPage] = useState<Page>("Traces");

  return (
    <div className="app">
      <header className="app-header">
        <h1>AgentOps</h1>
        <nav className="tabs">
          {PAGES.map((p) => (
            <button
              key={p}
              className={`tab ${p === page ? "active" : ""}`}
              onClick={() => setPage(p)}
            >
              {p}
            </button>
          ))}
        </nav>
      </header>
      <main className="app-main">
        {page === "Traces" && <TracesPage />}
        {page === "Metrics" && <MetricsPage />}
        {page === "Evals" && <EvalsPage />}
        {page === "Approvals" && <ApprovalsPage />}
      </main>
    </div>
  );
}

export default App;
