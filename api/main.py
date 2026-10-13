"""FastAPI backend for the AgentOps agent.

POST /chat            run the agent; if it pauses on a risky tool, returns
                       status "pending_approval" with a run_id instead of hanging.
GET  /approvals        list runs currently paused awaiting a human decision.
POST /approvals/{id}   resume a paused run with an approve/reject decision.
GET  /traces           recent runs with their spans (latency, tokens, errors), from SQLite.
GET  /metrics           Prometheus text exposition format.

Pending approvals live in an in-process dict -- fine for this single-process
demo, but they don't survive a restart; a real deployment would persist them
alongside the checkpointer.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from agent.graph import run_agent
from api import store
from api.metrics import ERROR_COUNT, GUARDRAIL_BLOCKS, PENDING_APPROVALS, REQUEST_COUNT, REQUEST_LATENCY, TOKEN_COUNTER

app = FastAPI(title="AgentOps API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_pending: dict[str, dict] = {}  # run_id -> {run_id, question, role, tool, args}


class ChatRequest(BaseModel):
    question: str
    role: str = "customer"


class ApprovalDecision(BaseModel):
    decision: str  # "approve" | "reject"
    reviewer: str


def _record(result: dict) -> None:
    trace = result["trace"]
    REQUEST_LATENCY.observe(trace["latency_ms"])
    TOKEN_COUNTER.inc(trace["tokens"])
    ERROR_COUNT.inc(trace["errors"])
    store.save_run(result["run_id"], result.get("question", ""), result.get("role", "customer"),
                   result["status"], result.get("answer", ""), result["spans"])


@app.post("/chat")
def chat(req: ChatRequest):
    result = run_agent(req.question, role=req.role)
    REQUEST_COUNT.labels(endpoint="chat", status=result["status"]).inc()
    if result.get("blocked"):
        GUARDRAIL_BLOCKS.inc()
    _record(result)

    if result["status"] == "pending_approval":
        entry = {"run_id": result["run_id"], "question": result.get("question", req.question),
                  "role": req.role, "tool": result["pending"]["tool"], "args": result["pending"]["args"]}
        _pending[result["run_id"]] = entry
        PENDING_APPROVALS.set(len(_pending))
        return {"status": "pending_approval", "run_id": result["run_id"], "pending": entry}

    return {"status": result["status"], "run_id": result["run_id"],
            "answer": result.get("answer", ""), "tool_results": result.get("tool_results", [])}


@app.get("/approvals")
def list_approvals():
    return {"pending": list(_pending.values())}


@app.post("/approvals/{run_id}")
def resolve_approval(run_id: str, body: ApprovalDecision):
    if run_id not in _pending:
        raise HTTPException(status_code=404, detail="No pending approval for that run_id")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    _pending.pop(run_id)
    PENDING_APPROVALS.set(len(_pending))
    decision = {"approved": body.decision == "approve", "reviewer": body.reviewer}
    result = run_agent(run_id=run_id, decision=decision)
    REQUEST_COUNT.labels(endpoint="approvals", status=result["status"]).inc()
    _record(result)

    return {"status": result["status"], "run_id": run_id,
            "answer": result.get("answer", ""), "tool_results": result.get("tool_results", [])}


@app.get("/traces")
def traces(limit: int = 20):
    return {"runs": store.recent_runs(limit)}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
