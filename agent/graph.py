"""LangGraph support agent: guard -> retrieve -> plan -> act -> answer.

`guard` runs first: it refuses prompt-injection attempts outright and
redacts PII (emails, phone numbers, credit cards) out of the question before
any other node sees it. `act` enforces RBAC and, for risky tools, pauses the
graph with a real LangGraph interrupt until a human approves or rejects --
there is no boolean flag, the graph genuinely stops running (checkpointed by
`MemorySaver`) until `run_agent` is called again with a decision for the same
run_id. Every node is traced (latency, tokens, errors).
"""
import os
import threading
import uuid
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent.llm import get_llm
from agent.rag import Retriever
from agent.tools import RISKY, TOOLS
from guardrails.injection import REFUSAL_MESSAGE, detect_injection
from guardrails.pii import redact_pii
from guardrails.rbac import is_allowed
from tracing.tracer import tracer


class State(TypedDict, total=False):
    question: str
    role: str
    blocked: bool
    block_reason: str
    pii_redacted: list[str]
    context: list[str]
    plan: list[dict]
    tool_results: list[dict[str, Any]]
    answer: str


_retriever = Retriever()
_llm = get_llm()
_run_lock = threading.Lock()  # serializes graph.invoke so concurrent API requests don't race on the shared tracer


def guard(state: State):
    with tracer.span("guard") as s:
        question = state["question"]
        flagged, reason = detect_injection(question)
        s["attrs"]["injection_flagged"] = flagged
        if flagged:
            s["attrs"]["reason"] = reason
            return {"blocked": True, "block_reason": reason, "answer": REFUSAL_MESSAGE}
        redacted, found = redact_pii(question)
        s["attrs"]["pii_entities"] = sorted(found)
        return {"blocked": False, "question": redacted, "pii_redacted": sorted(found)}


def _route_after_guard(state: State):
    return "blocked" if state.get("blocked") else "retrieve"


def retrieve(state: State):
    with tracer.span("retrieve") as s:
        top_k = int(os.getenv("AGENTOPS_TOP_K", "2"))
        ctx = _retriever.search(state["question"], top_k=top_k)
        s["attrs"]["hits"] = len(ctx)
    return {"context": ctx}


def plan(state: State):
    with tracer.span("plan") as s:
        calls, tok = _llm.plan(state["question"], state.get("context", []))
        s["tokens"] = tok
    return {"plan": calls}


def act(state: State):
    """Run each planned tool call. A risky tool the caller's role may use
    pauses the graph with `interrupt()` -- real human-in-the-loop, not a
    boolean flag -- until `run_agent` resumes it with an approve/reject
    decision. RBAC denial is checked first, so a role that can't use the
    tool at all never reaches the approval gate.
    """
    results = []
    for call in state.get("plan", []):
        name, args = call["name"], call["args"]
        if name in RISKY and is_allowed(state.get("role", "customer"), name):
            decision = interrupt({"tool": name, "args": args, "role": state.get("role", "customer")})
            with tracer.span(f"tool:{name}", **args) as s:
                s["attrs"]["reviewer"] = decision.get("reviewer")
                if decision.get("approved"):
                    results.append({"tool": name, "args": args, "status": "ran",
                                     "output": TOOLS[name](**args), "reviewer": decision.get("reviewer")})
                else:
                    results.append({"tool": name, "args": args, "status": "rejected",
                                     "output": {}, "reviewer": decision.get("reviewer")})
            continue
        with tracer.span(f"tool:{name}", **args):
            if not is_allowed(state.get("role", "customer"), name):
                results.append({"tool": name, "args": args, "status": "denied", "output": {}})
            else:
                results.append({"tool": name, "args": args, "status": "ran", "output": TOOLS[name](**args)})
    return {"tool_results": results}


def answer(state: State):
    with tracer.span("answer") as s:
        text, tok = _llm.answer(state["question"], state.get("context", []), state.get("tool_results", []))
        s["tokens"] = tok
    return {"answer": text}


def build_graph():
    g = StateGraph(State)
    g.add_node("guard", guard)
    g.add_node("retrieve", retrieve)
    g.add_node("plan", plan)
    g.add_node("act", act)
    g.add_node("answer", answer)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", _route_after_guard, {"blocked": END, "retrieve": "retrieve"})
    g.add_edge("retrieve", "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "answer")
    g.add_edge("answer", END)
    return g.compile(checkpointer=MemorySaver())


_graph = build_graph()


def run_agent(question: str | None = None, role: str = "customer",
              run_id: str | None = None, decision: dict | None = None) -> dict:
    """Start a new run, or resume a paused one.

    Fresh run: pass `question` (and optionally `role`). If the plan calls a
    risky tool the role may use, the graph pauses -- the returned dict has
    status "pending_approval" and a `run_id` to resume later; nothing beyond
    that point runs yet, and the checkpointed graph state is still paused
    waiting for a real resume.

    Resume: pass the same `run_id` plus `decision` (e.g.
    `{"approved": True, "reviewer": "alice"}`). The graph picks back up at
    the paused tool call and runs it (or records a rejection) through to the
    final answer.
    """
    with _run_lock:
        tracer.reset()
        thread_id = run_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        if decision is not None:
            state = dict(_graph.invoke(Command(resume=decision), config=config))
        else:
            state = dict(_graph.invoke({"question": question, "role": role}, config=config))

        interrupts = state.pop("__interrupt__", None)
        if interrupts:
            payload = interrupts[0].value
            # Synthesize the pending-approval answer for synchronous callers (evals,
            # tests) without touching the checkpoint -- the real interrupt stays
            # paused, ready to be resumed later with a genuine decision.
            pending_result = [{"tool": payload["tool"], "args": payload["args"],
                                "status": "pending_approval", "output": {}}]
            with tracer.span("answer") as s:
                text, tok = _llm.answer(state["question"], state.get("context", []), pending_result)
                s["tokens"] = tok
            return {**state, "answer": text, "tool_results": pending_result, "status": "pending_approval",
                    "run_id": thread_id, "pending": payload,
                    "trace": tracer.summary(), "spans": list(tracer.spans)}

        status = "blocked" if state.get("blocked") else "ok"
        return {**state, "status": status, "run_id": thread_id,
                "trace": tracer.summary(), "spans": list(tracer.spans)}
