"""LangGraph support agent: guard -> retrieve -> plan -> act -> answer.

`guard` runs first: it refuses prompt-injection attempts outright and
redacts PII (emails, phone numbers, credit cards) out of the question before
any other node sees it. `act` enforces RBAC and holds risky tools for human
approval. Every node is traced (latency, tokens, errors).
"""
import os
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

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
    approved: bool
    blocked: bool
    block_reason: str
    pii_redacted: list[str]
    context: list[str]
    plan: list[dict]
    tool_results: list[dict[str, Any]]
    answer: str


_retriever = Retriever()
_llm = get_llm()


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
    results = []
    for call in state.get("plan", []):
        name, args = call["name"], call["args"]
        with tracer.span(f"tool:{name}", **args):
            if not is_allowed(state.get("role", "customer"), name):
                results.append({"tool": name, "args": args, "status": "denied", "output": {}})
            elif name in RISKY and not state.get("approved"):
                results.append({"tool": name, "args": args, "status": "pending_approval", "output": {}})
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
    return g.compile()


_graph = build_graph()


def run_agent(question: str, role: str = "customer", approved: bool = False) -> dict:
    """Run one request. Returns the final state plus a trace summary."""
    tracer.reset()
    state = _graph.invoke({"question": question, "role": role, "approved": approved})
    return {**state, "trace": tracer.summary(), "spans": list(tracer.spans)}
