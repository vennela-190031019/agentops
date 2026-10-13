# AgentOps

A small support agent (LangGraph) with the "Ops" layer production teams need: **evals that fail CI on regressions, step-level tracing, and tool guardrails.**

> Status: week-1 scaffold. Agent, tracing, evals, RBAC, prompt-injection + PII guardrails, and CI gate work. Still to build: MCP server, FastAPI + React dashboard, Docker, Terraform.

## Eval results (clean baseline, 33 cases, deterministic mock LLM)

| Metric | Score |
|---|---|
| groundedness | 1.0 |
| tool_accuracy | 1.0 |
| correctness | 1.0 |
| pass_rate | 1.0 |

**Regression demo:** breaking retrieval (`AGENTOPS_TOP_K=0`) drops pass rate 1.0 -> 0.33 and the gate exits non-zero, failing the build.

## How it works

```
question -> guard (injection refusal + PII redaction) -> retrieve (RAG) -> plan -> act (RBAC + approval gate) -> answer
                 every step traced: latency, tokens, errors
```

- `agent/` LangGraph graph, retriever, tools, LLM adapters
- `guardrails/` role-based tool access, prompt-injection detection, PII redaction
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

## Known limits (honest)

- Groundedness is a token-overlap heuristic, not an LLM judge.
- Retriever is keyword + IDF; replace with embeddings.
- The mock LLM tests the pipeline (retrieval, tools, RBAC, approval), not language-model quality.
- Prompt-injection detection (`guardrails/injection.py`) is regex/heuristic, not a classifier; it catches known phrasings, not every jailbreak.
- PII redaction (`guardrails/pii.py`) covers emails, phone numbers and credit cards via Presidio pinned to spaCy's small `en_core_web_sm` model (fast enough for CI, unlike the default `en_core_web_lg`); it falls back to plain regex if presidio/spacy aren't installed. Other PII types (names, addresses, SSNs) aren't covered yet.
