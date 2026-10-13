"""LLM adapters.

MockLLM  - deterministic, rule-based. Used in CI so evals are free, fast and
           reproducible. It exercises the whole pipeline (retrieval, tools,
           RBAC, approval), so a change to ANY of those can regress the evals.
OllamaLLM - local model via Ollama's HTTP API (free). Select with
           AGENTOPS_LLM=ollama. NOTE: not yet tested end to end.
"""
import json
import os
import re
import urllib.request

ORDER_RE = re.compile(r"ORD-\d+", re.I)
NO_INFO = "I don't have information on that."


def _count_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3) + 1


class MockLLM:
    def plan(self, question: str, context: list[str]):
        m = ORDER_RE.search(question)
        if not m:
            return [], _count_tokens(question)
        order_id = m.group(0).upper()
        q = question.lower()
        tool = "issue_refund" if "refund" in q else "lookup_order"
        return [{"name": tool, "args": {"order_id": order_id}}], _count_tokens(question)

    def answer(self, question: str, context: list[str], tool_results: list[dict]):
        if tool_results:
            parts = []
            for r in tool_results:
                out = r["output"]
                oid = out.get("order_id") or r["args"].get("order_id")
                if r["status"] == "denied":
                    parts.append(f"You are not permitted to use {r['tool']}.")
                elif r["status"] == "pending_approval":
                    parts.append(f"The refund for order {oid} is pending human approval.")
                elif out.get("status") == "not_found":
                    parts.append(f"I couldn't find order {oid}.")
                elif out.get("status") == "ok":
                    s = f"Order {oid} is {out['order_status']}"
                    if out.get("carrier"):
                        s += f" via {out['carrier']}"
                    if out.get("eta"):
                        s += f", expected {out['eta']}"
                    parts.append(s + ".")
                elif out.get("status") == "refunded":
                    parts.append(f"The refund for order {oid} has been issued.")
            text = " ".join(parts)
        elif context:
            text = " ".join(context[:2])
        else:
            text = NO_INFO
        return text, _count_tokens(question) + _count_tokens(text)


class OllamaLLM:
    def __init__(self, model=None, host=None):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def _chat(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "stream": False,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)["message"]["content"]

    def plan(self, question, context):
        m = ORDER_RE.search(question)
        if not m:
            return [], _count_tokens(question)
        out = self._chat(
            'Reply with ONLY one word: "lookup_order" to check order status or '
            f'"issue_refund" to refund it.\nRequest: {question}')
        tool = "issue_refund" if "refund" in out.lower() else "lookup_order"
        return [{"name": tool, "args": {"order_id": m.group(0).upper()}}], _count_tokens(question + out)

    def answer(self, question, context, tool_results):
        if not tool_results and not context:
            return NO_INFO, _count_tokens(question)
        prompt = ("Answer ONLY from the facts below. If they don't answer it, say "
                  f"\"{NO_INFO}\"\nFacts: {context} {tool_results}\nQuestion: {question}")
        out = self._chat(prompt)
        return out, _count_tokens(prompt + out)


def get_llm():
    return OllamaLLM() if os.getenv("AGENTOPS_LLM") == "ollama" else MockLLM()
