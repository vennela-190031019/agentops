"""FastAPI backend for the AgentOps agent.

POST /chat            run the agent; if it pauses on a risky tool, returns
                       status "pending_approval" with a run_id instead of hanging.
GET  /approvals        list runs currently paused awaiting a human decision.
POST /approvals/{id}   resume a paused run with an approve/reject decision.
GET  /traces           recent runs with their spans (latency, tokens, errors), from SQLite.
GET  /health            liveness check -- open, no auth.
GET  /metrics           Prometheus text exposition format -- open, no auth.

Every other endpoint requires an `X-API-Key` header (see `api/auth.py`): the
caller's role is derived from the key, never from the request body, and
`/approvals*` is restricted to the "reviewer" role. Pending approvals are
stored in SQLite (`api/store.py`), not an in-process dict, so they -- and the
underlying LangGraph checkpoint -- survive a server restart.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from agent.graph import run_agent
from api import store
from api.auth import Auth, ChatAuth, ReviewerAuth
from api.metrics import ERROR_COUNT, GUARDRAIL_BLOCKS, PENDING_APPROVALS, REQUEST_COUNT, REQUEST_LATENCY, TOKEN_COUNTER

app = FastAPI(title="AgentOps API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
PENDING_APPROVALS.set(len(store.list_pending()))


class ChatRequest(BaseModel):
    question: str


class ApprovalDecision(BaseModel):
    decision: str  # "approve" | "reject"


def _record(result: dict) -> None:
    trace = result["trace"]
    REQUEST_LATENCY.observe(trace["latency_ms"])
    TOKEN_COUNTER.inc(trace["tokens"])
    ERROR_COUNT.inc(trace["errors"])
    store.save_run(result["run_id"], result.get("question", ""), result.get("role", "customer"),
                   result["status"], result.get("answer", ""), result["spans"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest, auth: ChatAuth):
    role, _ = auth
    result = run_agent(req.question, role=role)
    REQUEST_COUNT.labels(endpoint="chat", status=result["status"]).inc()
    if result.get("blocked"):
        GUARDRAIL_BLOCKS.inc()
    _record(result)

    if result["status"] == "pending_approval":
        question = result.get("question", req.question)
        store.save_pending(result["run_id"], question, role,
                            result["pending"]["tool"], result["pending"]["args"])
        PENDING_APPROVALS.set(len(store.list_pending()))
        return {"status": "pending_approval", "run_id": result["run_id"],
                "pending": store.get_pending(result["run_id"])}

    return {"status": result["status"], "run_id": result["run_id"],
            "answer": result.get("answer", ""), "tool_results": result.get("tool_results", [])}


@app.get("/approvals")
def list_approvals(auth: ReviewerAuth):
    return {"pending": store.list_pending()}


@app.post("/approvals/{run_id}")
def resolve_approval(run_id: str, body: ApprovalDecision, auth: ReviewerAuth):
    if store.get_pending(run_id) is None:
        raise HTTPException(status_code=404, detail="No pending approval for that run_id")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    _, reviewer_key = auth  # identity comes from the key, never the request body
    store.delete_pending(run_id)
    PENDING_APPROVALS.set(len(store.list_pending()))
    decision = {"approved": body.decision == "approve", "reviewer": reviewer_key}
    result = run_agent(run_id=run_id, decision=decision)
    REQUEST_COUNT.labels(endpoint="approvals", status=result["status"]).inc()
    _record(result)

    return {"status": result["status"], "run_id": run_id,
            "answer": result.get("answer", ""), "tool_results": result.get("tool_results", [])}


@app.get("/traces")
def traces(auth: Auth, limit: int = 20):
    return {"runs": store.recent_runs(limit)}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
