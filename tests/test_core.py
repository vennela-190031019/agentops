from agent.graph import run_agent
from agent.rag import Retriever
from evals.scorers import correctness, groundedness, tool_accuracy
from guardrails.rbac import is_allowed
from tracing.tracer import Tracer


def test_rbac():
    assert is_allowed("support_agent", "issue_refund")
    assert not is_allowed("customer", "issue_refund")
    assert not is_allowed("unknown", "lookup_order")


def test_retriever_finds_specific_chunk():
    assert "non-refundable" in Retriever().search("refund on a digital download?")[0]


def test_tracer_records_latency_tokens_and_errors():
    t = Tracer()
    with t.span("ok") as s:
        s["tokens"] = 10
    try:
        with t.span("boom"):
            raise ValueError("x")
    except ValueError:
        pass
    sm = t.summary()
    assert sm["spans"] == 2 and sm["tokens"] == 10 and sm["errors"] == 1


def test_risky_tool_pauses_then_runs_on_approval():
    out = run_agent("Please refund order ORD-1003", role="support_agent")
    assert out["status"] == "pending_approval"
    assert out["tool_results"][0]["status"] == "pending_approval"
    out = run_agent(run_id=out["run_id"], decision={"approved": True, "reviewer": "alice"})
    assert out["status"] == "ok"
    assert out["tool_results"][0]["status"] == "ran"
    assert out["tool_results"][0]["reviewer"] == "alice"
    assert "issued" in out["answer"]


def test_risky_tool_rejected_never_runs():
    out = run_agent("Please refund order ORD-1003", role="support_agent")
    run_id = out["run_id"]
    out = run_agent(run_id=run_id, decision={"approved": False, "reviewer": "bob"})
    assert out["tool_results"][0]["status"] == "rejected"
    assert out["tool_results"][0]["output"] == {}
    assert "rejected" in out["answer"]


def test_customer_cannot_refund():
    out = run_agent("Please refund order ORD-1003", role="customer")
    assert out["tool_results"][0]["status"] == "denied"


def test_scorers():
    assert tool_accuracy(["a"], ["a"]) == 1.0 and tool_accuracy(["a"], []) == 0.0
    assert correctness("It takes 5 days", ["5 days"]) == 1.0
    assert groundedness("Standard shipping takes 5 days", ["Standard shipping takes 5 days"], []) == 1.0
    assert groundedness("The moon is made of cheese", ["Standard shipping takes 5 days"], []) == 0.0
