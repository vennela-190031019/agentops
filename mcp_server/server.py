"""MCP server exposing two read-only agent tools over stdio.

Only `search_docs` and `lookup_order` are exposed. `issue_refund` is
deliberately NOT here: it's a risky tool that must stay behind RBAC and
human approval (see agent/graph.py's `act` node), not reachable via MCP.

Every tool argument runs through the same guardrails the LangGraph agent
uses (guardrails/injection.py, guardrails/pii.py): prompt-injection attempts
raise a safe error instead of running the tool, and PII is redacted out of
the argument before it reaches the retriever or the order lookup.
"""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agent.rag import Retriever
from agent.tools import lookup_order as _lookup_order
from guardrails.injection import REFUSAL_MESSAGE, detect_injection
from guardrails.pii import redact_pii

mcp = FastMCP("agentops")
_retriever = Retriever()

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _guarded(text: str) -> str:
    """Run the injection/PII guardrails on a tool argument.

    Raises ValueError (surfaced by MCP as a safe tool-error, no traceback)
    if the input is flagged as prompt injection. Otherwise returns the
    PII-redacted text.
    """
    flagged, _ = detect_injection(text)
    if flagged:
        raise ValueError(REFUSAL_MESSAGE)
    redacted, _ = redact_pii(text)
    return redacted


@mcp.tool(annotations=_READ_ONLY)
def search_docs(query: str) -> list[str]:
    """Search the support docs (shipping, refunds, returns, account) and return the top matching chunks."""
    return _retriever.search(_guarded(query), top_k=2)


@mcp.tool(annotations=_READ_ONLY)
def lookup_order(order_id: str) -> dict:
    """Look up an order's shipping status by order ID (e.g. ORD-1001)."""
    return _lookup_order(_guarded(order_id))


if __name__ == "__main__":
    mcp.run()
