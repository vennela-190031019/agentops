"""Prometheus metrics for the API. Free, in-process, no external collector needed."""
from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter("agentops_requests", "Chat/approval requests handled", ["endpoint", "status"])
ERROR_COUNT = Counter("agentops_span_errors", "Spans that recorded an error")
REQUEST_LATENCY = Histogram(
    "agentops_request_latency_ms", "End-to-end request latency in milliseconds",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
)
TOKEN_COUNTER = Counter("agentops_tokens", "Tokens consumed across all runs")
PENDING_APPROVALS = Gauge("agentops_pending_approvals", "Approvals currently awaiting a human decision")
GUARDRAIL_BLOCKS = Counter("agentops_guardrail_blocks", "Requests blocked by the prompt-injection guardrail")
