"""Minimal span tracer: latency, token count, errors per step. Exports JSONL.

Deliberately dependency-free so it runs in CI. The span shape mirrors
OpenTelemetry (name, attributes, duration, error) so it can be swapped for
the OTel SDK later without touching the agent code.
"""
import json
import os
import time
from contextlib import contextmanager

COST_PER_1K_TOKENS = float(os.getenv("AGENTOPS_COST_PER_1K_TOKENS", "0"))


class Tracer:
    def __init__(self):
        self.spans = []

    def reset(self):
        self.spans = []

    @contextmanager
    def span(self, name, **attrs):
        s = {"name": name, "attrs": attrs, "tokens": 0, "error": None}
        t0 = time.perf_counter()
        try:
            yield s
        except Exception as e:  # record, then re-raise
            s["error"] = repr(e)
            raise
        finally:
            s["latency_ms"] = (time.perf_counter() - t0) * 1000
            self.spans.append(s)

    def summary(self):
        tokens = sum(s["tokens"] for s in self.spans)
        return {
            "spans": len(self.spans),
            "latency_ms": round(sum(s["latency_ms"] for s in self.spans), 3),
            "tokens": tokens,
            "cost_usd": round(tokens / 1000 * COST_PER_1K_TOKENS, 6),
            "errors": sum(1 for s in self.spans if s["error"]),
        }

    def dump(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a") as f:
            for s in self.spans:
                f.write(json.dumps(s) + "\n")


tracer = Tracer()
