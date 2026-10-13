# AgentOps

A small support agent (LangGraph) with the "Ops" layer production teams need: **evals that fail CI on regressions, step-level tracing, and tool guardrails.**

> Status: week-1 scaffold. Agent, tracing, evals, RBAC, prompt-injection + PII guardrails, embedding retrieval, an MCP server, a FastAPI backend with real human-in-the-loop approval, and CI gate work. Still to build: React dashboard, Docker, Terraform.

## Eval results (clean baseline, 39 cases, deterministic mock LLM)

| Metric | Score |
|---|---|
| groundedness | 1.0 |
| tool_accuracy | 1.0 |
| correctness | 1.0 |
| pass_rate | 1.0 |

**Regression demo:** breaking retrieval (`AGENTOPS_TOP_K=0`) drops pass rate 1.0 -> 0.33 and the gate exits non-zero, failing the build.

Two more cases (`refund-approved`, `refund-rejected`) exercise the full approve/reject round trip end to end -- 41/41 pass; `evals/baseline.json` stays pinned to the original 39 so the regression gate keeps comparing against the same bar.

## How it works

```
question -> guard (injection refusal + PII redaction) -> retrieve (RAG) -> plan -> act (RBAC + approval gate) -> answer
                 every step traced: latency, tokens, errors
```

`act` holds risky tools (`issue_refund`) for real human approval: it's a LangGraph `interrupt()`, checkpointed with `MemorySaver`, not a boolean flag. The graph genuinely pauses -- nothing downstream of the paused tool call runs -- until something resumes it with a decision for that run's `thread_id`. Rejecting means the tool call is skipped entirely and the answer says it was rejected.

- `agent/` LangGraph graph, retriever, tools, LLM adapters
- `guardrails/` role-based tool access, prompt-injection detection, PII redaction
- `mcp_server/` MCP server exposing read-only tools (`search_docs`, `lookup_order`) to MCP clients like Claude Desktop
- `tracing/` span tracer (OpenTelemetry-shaped, JSONL export)
- `evals/` dataset, scorers, runner, regression gate (`compare.py`)
- `tests/` unit tests

## Run

```bash
pip install -r requirements.txt
pytest -q
python -m evals.run_evals        # score the agent
python -m evals.compare          # exit 1 if quality dropped vs evals/baseline.json
python -m evals.compare --update # accept current scores as the new baseline
```

CI (`.github/workflows/ci.yml`) runs the same on every push. LLM: a deterministic mock by default (free, reproducible); set `AGENTOPS_LLM=ollama` for a local model (adapter not yet tested).

## API (FastAPI)

```bash
uvicorn api.main:app --reload --port 8000
```

CORS is open for `http://localhost:5173` (the React dev server, not yet built). Traces are stored in a local SQLite file (`agentops.db`, override with `AGENTOPS_DB_PATH`).

| Endpoint | Description |
|---|---|
| `POST /chat` | `{question, role}` -> runs the agent. If it pauses on a risky tool, returns `{status: "pending_approval", run_id, pending}` instead of the tool running. |
| `GET /approvals` | List runs currently paused awaiting a human decision. |
| `POST /approvals/{run_id}` | `{decision: "approve"\|"reject", reviewer}` -> resumes the paused graph. Approve runs the tool; reject skips it and the answer says so. 404 if `run_id` isn't pending. |
| `GET /traces` | Recent runs (`?limit=`) with their spans: latency, tokens, errors, from SQLite. |
| `GET /metrics` | Prometheus text format: request count, error count, a latency histogram, a token counter, a pending-approvals gauge, and a guardrail-block counter. |

Pending approvals are tracked in an in-process dict, so they don't survive a server restart -- fine for this scaffold, not for production.

```bash
curl -s localhost:8000/chat -d '{"question": "Please refund order ORD-1003", "role": "support_agent"}' -H 'Content-Type: application/json'
# -> {"status": "pending_approval", "run_id": "...", "pending": {"tool": "issue_refund", "args": {"order_id": "ORD-1003"}, ...}}

curl -s localhost:8000/approvals/<run_id> -X POST -d '{"decision": "approve", "reviewer": "alice"}' -H 'Content-Type: application/json'
# -> {"status": "ok", "answer": "The refund for order ORD-1003 has been issued.", ...}
```

## MCP server

![Claude Code calling the AgentOps MCP server](assets/mcp-demo.png)

`mcp_server/server.py` exposes two **read-only** tools over MCP: `search_docs(query)` (wraps the `Retriever`) and `lookup_order(order_id)` (wraps the order-lookup tool). `issue_refund` is deliberately not exposed here -- it's a risky tool and stays behind RBAC + human approval in the LangGraph agent, not reachable via MCP. Every tool argument is run through the same injection/PII guardrails as the agent: a flagged prompt-injection attempt raises a safe tool error (no traceback leaked), and PII is redacted before the argument reaches the retriever or order lookup.

Run it standalone over stdio:

```bash
python -m mcp_server.server
```

To connect it to Claude Desktop, add this to `claude_desktop_config.json` (use an absolute path to your checkout and Python):

```json
{
  "mcpServers": {
    "agentops": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/agentops"
    }
  }
}
```

## Known limits (honest)

- Groundedness is a token-overlap heuristic, not an LLM judge.
- Retriever uses fastembed/MiniLM embeddings with a keyword+IDF fallback (`agent/rag.py`); a small hybrid tie-break rule handles near-duplicate bullets that cosine similarity alone ranks wrong, and a similarity floor makes it abstain on off-topic questions instead of forcing in irrelevant context.
- The mock LLM tests the pipeline (retrieval, tools, RBAC, approval), not language-model quality.
- Prompt-injection detection (`guardrails/injection.py`) is regex/heuristic, not a classifier; it catches known phrasings, not every jailbreak.
- PII redaction (`guardrails/pii.py`) covers emails, phone numbers and credit cards via Presidio pinned to spaCy's small `en_core_web_sm` model (fast enough for CI, unlike the default `en_core_web_lg`); it falls back to plain regex if presidio/spacy aren't installed. Other PII types (names, addresses, SSNs) aren't covered yet.
- The MCP server reuses the same regex/heuristic guardrails as the agent, so it inherits the same blind spots; it has no RBAC/role concept of its own, which is why the risky `issue_refund` tool is simply never exposed rather than gated per-role.
- The approval checkpointer (`MemorySaver`) and the API's pending-approvals dict are both in-process memory: a paused run doesn't survive a server restart. A real deployment would swap in a persistent LangGraph checkpointer and back the pending-approvals list with the same store.
