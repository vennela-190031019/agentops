# AgentOps

A small support agent (LangGraph) wrapped in the operational layer a real deployment needs: evals that fail CI on regressions, step-level tracing, tool guardrails, and a human-in-the-loop approval gate for risky actions. It exists to show what "ops" around an LLM agent looks like end to end, not just the agent itself.

## Architecture

```mermaid
flowchart LR
    Q[question] --> G[guard\ninjection + PII]
    G --> RT[retrieve\nRAG]
    RT --> PL[plan]
    PL --> AC[act\nRBAC + tools]
    AC -->|risky tool| APR{{human approval gate}}
    APR -->|approve/reject| AC
    AC --> AN[answer]

    subgraph obs [Observability]
        TR[tracing]
        PROM[Prometheus]
        GRAF[Grafana]
    end
    G -.-> TR
    RT -.-> TR
    PL -.-> TR
    AC -.-> TR
    TR --> PROM --> GRAF

    subgraph iface [Interfaces]
        API[FastAPI]
        DASH[Dashboard]
        MCP[MCP server]
    end
    API --> Q
    AN --> API
    API --> DASH
    MCP -->|search_docs, lookup_order| RT
```

`act` holds risky tools (`issue_refund`) for real human approval: it's a LangGraph `interrupt()`, checkpointed to SQLite (`SqliteSaver`), not a boolean flag. The graph genuinely pauses -- nothing downstream of the paused tool call runs -- until something resumes it with a decision for that run's `thread_id`. Rejecting means the tool call is skipped entirely and the answer says it was rejected. Because the checkpoint is on disk, a pending approval survives a server restart.

- `agent/` LangGraph graph, retriever, tools, LLM adapters
- `guardrails/` role-based tool access, prompt-injection detection, PII redaction
- `mcp_server/` MCP server exposing read-only tools (`search_docs`, `lookup_order`) to MCP clients like Claude Desktop
- `tracing/` span tracer (OpenTelemetry-shaped, JSONL export)
- `evals/` dataset, scorers, runner, regression gate (`compare.py`)
- `tests/` unit tests
- `infra/` prometheus/grafana provisioning for docker-compose, and `infra/terraform/` (ECS Fargate deployment, validated in CI, not deployed)

## Screenshots

| Traces | Approvals (pending) |
|---|---|
| ![Traces](assets/dashboard-traces.png) | ![Pending approvals](assets/dashboard-approvals-pending.png) |

| Approvals (approved) | Evals |
|---|---|
| ![Approved approvals](assets/dashboard-approvals-approved.png) | ![Eval history](assets/dashboard-evals.png) |

| Grafana | MCP |
|---|---|
| ![Grafana dashboard](assets/grafana.png) | ![Claude Code calling the AgentOps MCP server](assets/mcp-demo.png) |

## Eval results

Clean baseline, 39 pinned cases, deterministic mock LLM (`evals/baseline.json`):

| Metric | Score |
|---|---|
| groundedness | 1.0 |
| tool_accuracy | 1.0 |
| correctness | 1.0 |
| pass_rate | 1.0 |

Two more cases (`refund-approved`, `refund-rejected`) exercise the full approve/reject round trip end to end -- 41/41 pass across the full set; `evals/baseline.json` stays pinned to the original 39 so the regression gate keeps comparing against the same bar.

**Regression demo** (`evals/history.json`): a deliberate break (dropping `AGENTOPS_TOP_K` to 0, killing retrieval) dropped `pass_rate` from `1.0` to `0.3902` and `correctness` from `1.0` to `0.3902`. `evals/compare.py` caught it and exited non-zero, failing CI, before the fix landed.

## Quickstart

```bash
cp .env.example .env   # AGENTOPS_API_KEYS, VITE_API_KEY, optionally GRAFANA_ADMIN_PASSWORD

pip install -r requirements.txt
pytest -q
python -m evals.run_evals        # score the agent
python -m evals.compare          # exit 1 if quality dropped vs evals/baseline.json
python -m evals.compare --update # accept current scores as the new baseline

uvicorn api.main:app --reload --port 8000   # backend, http://localhost:8000

cd dashboard && npm ci && npm run dev       # dashboard dev server, http://localhost:5173

docker compose up -d --build                # full stack: api, dashboard, prometheus, grafana
```

`AGENTOPS_API_KEYS` is a JSON `{key: role}` map (roles: `customer`, `support_agent`, `reviewer`); if unset, the API falls back to dev keys (`dev-customer-key`, `dev-support-agent-key`, `dev-reviewer-key`) and logs a warning on every request. `VITE_API_KEY` should be one of the `reviewer`-role keys so the dashboard's Approvals page works. **`VITE_API_KEY` is baked into the dashboard's JS bundle at build time (Vite env vars always are)** -- change it and you must rebuild the dashboard image (`docker compose up -d --build dashboard`) or rerun `npm run build`, not just restart the container.

CI (`.github/workflows/ci.yml`) runs the same pytest/evals/compare steps on every push.

## API (FastAPI)

CORS is open for `http://localhost:5173` (the React dev server). Traces are stored in a local SQLite file (`agentops.db`, override with `AGENTOPS_DB_PATH`).

### Auth

Every endpoint except `/health` and `/metrics` requires an `X-API-Key` header. The key maps to a role server-side -- **the role is never taken from the request body**, so a customer can't just send `"role": "support_agent"` to unlock the refund tool (see `tests/test_api.py::test_role_cannot_be_spoofed_via_request_body`).

Three roles:
- **customer** -- can `/chat`; `issue_refund` is denied outright (RBAC).
- **support_agent** -- can `/chat`; `issue_refund` pauses for approval.
- **reviewer** -- can *only* `/approvals` and `/approvals/{run_id}`; 403 on `/chat`. `customer`/`support_agent` get 403 on both approval endpoints. The reviewer's identity recorded on an approve/reject decision is their API key, never a `reviewer` field in the request body (same anti-spoofing principle as role).

| Endpoint | Auth | Description |
|---|---|---|
| `GET /health` | open | Liveness check. |
| `GET /metrics` | open | Prometheus text format: request count, error count, a latency histogram, a token counter, a pending-approvals gauge, and a guardrail-block counter. |
| `POST /chat` | customer, support_agent | `{question}` -> runs the agent as the caller's key's role. If it pauses on a risky tool, returns `{status: "pending_approval", run_id, pending}` instead of the tool running. |
| `GET /approvals` | reviewer | List runs currently paused awaiting a human decision. |
| `POST /approvals/{run_id}` | reviewer | `{decision: "approve"\|"reject"}` -> resumes the paused graph. Approve runs the tool; reject skips it and the answer says so. 404 if `run_id` isn't pending. |
| `GET /traces` | any valid key | Recent runs (`?limit=`) with their spans: latency, tokens, errors, from SQLite. |
| `GET /evals` | any valid key | Eval history from the committed `evals/history.json` -- one entry per run of `python -m evals.run_evals`. |

```bash
curl -s localhost:8000/chat -d '{"question": "Please refund order ORD-1003"}' -H 'Content-Type: application/json' -H 'X-API-Key: agent-key'
# -> {"status": "pending_approval", "run_id": "...", "pending": {"tool": "issue_refund", "args": {"order_id": "ORD-1003"}, ...}}

curl -s localhost:8000/approvals/<run_id> -X POST -d '{"decision": "approve"}' -H 'Content-Type: application/json' -H 'X-API-Key: reviewer-key'
# -> {"status": "ok", "answer": "The refund for order ORD-1003 has been issued.", ...}
```

Pending approvals are stored in SQLite (`api/store.py`'s `pending_approvals` table), and the LangGraph checkpoint itself is also SQLite -- so a pending approval, and the ability to resume it, both survive a server restart. What does *not* survive a restart: in-flight Prometheus counters (process-local by design) and anything mid-request.

## Dashboard (React + Vite)

Four tabs, each talking directly to the FastAPI backend (no separate dashboard backend/database):

- **Traces** -- table of recent runs from `GET /traces`; click a row to see that run's spans as a proportional-width timeline (name, latency, tokens, error).
- **Metrics** -- latency, token usage (+ an editable $/1K-token rate for an estimated cost figure, since the mock LLM is free and the real rate is a backend env var the API doesn't expose), span errors, and guardrail blocks, each charted over recent runs from `GET /traces` (Recharts). Prometheus's `/metrics` is a point-in-time snapshot, not a time series, so "over time" here is derived from the timestamped run history instead.
- **Evals** -- table + line chart of `GET /evals` (eval history): pass rate, groundedness, tool accuracy, correctness per run, with any regressed run (same tolerance-vs-baseline definition `evals/compare.py`'s gate uses) highlighted red.
- **Approvals** -- queue from `GET /approvals` with Approve/Reject buttons calling `POST /approvals/{run_id}`; resolved items show the agent's real answer, not just a status flip.

`npm run lint` (oxlint) and `npm run build` (`tsc -b && vite build`) both run in CI (`.github/workflows/ci.yml`, `dashboard` job).

## MCP server

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

## Docker / docker-compose

```bash
cp .env.example .env     # fill in AGENTOPS_API_KEYS, VITE_API_KEY, Grafana admin password
docker compose up -d --build
```

| Service | URL | What |
|---|---|---|
| `api` | http://localhost:8000 | FastAPI backend (`Dockerfile`, non-root, fastembed model pre-downloaded at build time so the first request isn't a cold-start model fetch). |
| `dashboard` | http://localhost:5173 | React dashboard, built and served as static files via nginx (`dashboard/Dockerfile`, multi-stage node build -> nginx). `VITE_API_URL`/`VITE_API_KEY` are baked into the JS bundle at build time from `.env`. |
| `prometheus` | http://localhost:9090 | Scrapes the API's `/metrics` every 15s (`infra/prometheus/prometheus.yml`). |
| `grafana` | http://localhost:3001 | Pre-provisioned with the Prometheus datasource and an "AgentOps" dashboard (`infra/grafana/`): request rate, error rate, p95 latency, tokens, pending approvals, guardrail blocks. Login from `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD` in `.env` (defaults to `admin`/`admin` -- change it before exposing the stack beyond your own machine). |

No secrets live in `docker-compose.yml` itself -- `AGENTOPS_API_KEYS`, `VITE_API_KEY`, and the Grafana password are all read from `.env` (gitignored; `.env.example` is the committed template). SQLite data (traces, pending approvals, the LangGraph checkpoint DB) lives on a named volume (`agentops-data` -> `/app/data` in the container) so approvals survive `docker compose down` / `up` (not `down -v`, which deletes volumes).

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop and wipe all volumes (SQLite data, Prometheus/Grafana state)
```

## Infrastructure (Terraform, validated only -- not deployed)

`infra/terraform/` describes an ECS Fargate deployment of the API: an ECR repository, a CloudWatch log group, an ALB with a target group and HTTP listener, security groups scoping the tasks to ALB-only traffic, an IAM execution role (ECR pull + CloudWatch logs + reading `AGENTOPS_API_KEYS` from a SecureString SSM parameter) and task role, and an ECS Fargate service/task definition. All free-tier-eligible AWS resource types -- no cost is intentionally incurred, because **nothing here is ever applied**.

This Terraform has been run locally through `terraform fmt`, `terraform init -backend=false`, and `terraform validate` -- it's syntactically correct and internally consistent. It has never been planned or applied against a real AWS account, there's no backend/state configured, and CI only runs `fmt -check` + `validate` (see the `terraform` job in `.github/workflows/ci.yml`) -- never `plan` or `apply`, and no AWS credentials are configured anywhere in this repo. Known gap if this were ever deployed for real: Fargate's task filesystem is ephemeral, so the SQLite-based trace/approval/checkpoint storage would not survive a task replacement the way the docker-compose named volume does locally -- EFS or a managed database would be needed first.

## Known limits (honest)

- The CI LLM is a deterministic mock, not a real model (free, reproducible); `AGENTOPS_LLM=ollama` exists for a local model but that adapter is untested.
- Groundedness is a token-overlap heuristic, not an LLM judge.
- Guardrail and retriever thresholds (injection detection, similarity floors, tie-break rules in `agent/rag.py`) were tuned on the 41-case eval set, not held out against a separate set.
- Prompt-injection detection (`guardrails/injection.py`) is regex/heuristic, not a classifier; it catches known phrasings, not every jailbreak.
- PII redaction (`guardrails/pii.py`) covers emails, phone numbers and credit cards via Presidio pinned to spaCy's small `en_core_web_sm` model; it falls back to plain regex if presidio/spacy aren't installed. Other PII types (names, addresses, SSNs) aren't covered yet.
- `issue_refund` is deliberately not exposed over MCP -- the MCP server only exposes read-only tools and has no RBAC/role concept of its own, so the risky tool is simply never reachable there rather than gated per-role.
- Terraform was validated with `fmt`/`validate` only; it has never been planned or applied against real AWS infrastructure.
- API-key auth is a single static `key -> role` map in an env var, checked in plaintext against the header; it has no expiry, rotation, or per-key rate limiting. The dev API keys (`dev-customer-key`, `dev-support-agent-key`, `dev-reviewer-key`) are for local use only, never a real deployment.
- The reviewer "identity" recorded on an approval decision is just the raw API key string, not a separate human name/account; two reviewers must use two different keys to be distinguishable in a trace.
- The dashboard's "cost" figure is tokens × a rate you type in, not a real bill; the Metrics page's charts only cover whatever's in the last `?limit=` runs from `/traces`, not true unbounded history.
