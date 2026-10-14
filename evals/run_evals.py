"""Run the eval set against the agent and write evals/results.json.

Usage:  python -m evals.run_evals
"""
import datetime
import json
import os
import statistics

import yaml

from agent.graph import run_agent
from evals.compare import BASELINE, QUALITY, TOLERANCE
from evals.scorers import correctness, groundedness, pii_clean, refused, tool_accuracy

HERE = os.path.dirname(__file__)
CASES = os.path.join(HERE, "datasets", "cases.yaml")
OUT = os.path.join(HERE, "results.json")
HISTORY = os.path.join(HERE, "history.json")


def run():
    cases = yaml.safe_load(open(CASES))
    rows = []
    for c in cases:
        out = run_agent(c["question"], role=c.get("role", "customer"))
        if out.get("status") == "pending_approval" and c.get("approval_decision"):
            # Two-step case: a human reviewer resumes the paused run.
            decision = {"approved": c["approval_decision"] == "approve", "reviewer": "eval-bot"}
            out = run_agent(run_id=out["run_id"], decision=decision)
        used = [r["tool"] for r in out.get("tool_results", [])]
        blocked = out.get("blocked", False)

        if c.get("expected_refused"):
            # Groundedness/correctness don't apply to a refusal: there's no
            # context or tool output to ground against. Score it purely on
            # whether the guard actually blocked the request.
            rows.append({
                "id": c["id"], "answer": out["answer"], "tools": used,
                "groundedness": 1.0, "tool_accuracy": 1.0, "correctness": 1.0,
                "passed": refused(blocked, out["answer"]) == 1.0,
                "latency_ms": out["trace"]["latency_ms"], "tokens": out["trace"]["tokens"],
            })
            continue

        g = groundedness(out["answer"], out.get("context", []), out.get("tool_results", []))
        t = tool_accuracy(c.get("expected_tools", []), used)
        k = correctness(out["answer"], c.get("expected_contains", []))
        passed = not blocked and g >= 0.99 and t == 1.0 and k == 1.0
        if c.get("expected_pii_redacted"):
            passed = passed and pii_clean(out.get("question", ""), out["answer"]) == 1.0
        rows.append({
            "id": c["id"], "answer": out["answer"], "tools": used,
            "groundedness": g, "tool_accuracy": t, "correctness": k,
            "passed": passed,
            "latency_ms": out["trace"]["latency_ms"], "tokens": out["trace"]["tokens"],
        })
    lat = sorted(r["latency_ms"] for r in rows)
    metrics = {
        "groundedness": round(statistics.mean(r["groundedness"] for r in rows), 4),
        "tool_accuracy": round(statistics.mean(r["tool_accuracy"] for r in rows), 4),
        "correctness": round(statistics.mean(r["correctness"] for r in rows), 4),
        "pass_rate": round(sum(r["passed"] for r in rows) / len(rows), 4),
        "p95_latency_ms": round(lat[int(0.95 * (len(lat) - 1))], 3),
        "avg_tokens": round(statistics.mean(r["tokens"] for r in rows), 1),
    }
    result = {"metrics": metrics, "cases": rows}
    json.dump(result, open(OUT, "w"), indent=2)
    _append_history(metrics)
    return result


def _is_regression(metrics: dict) -> bool:
    """Same definition evals/compare.py's gate uses, so the dashboard's
    "regressed" flag can never disagree with what actually failed the build."""
    if not os.path.exists(BASELINE):
        return False
    base = json.load(open(BASELINE))["metrics"]
    return any(metrics[m] < base[m] - TOLERANCE for m in QUALITY)


def _append_history(metrics: dict) -> None:
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pass_rate": metrics["pass_rate"],
        "metrics": metrics,
        "regressed": _is_regression(metrics),
    }
    history = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []
    history.append(entry)
    json.dump(history, open(HISTORY, "w"), indent=2)


def print_table(result):
    print("| Metric | Score |\n|---|---|")
    for k, v in result["metrics"].items():
        print(f"| {k} | {v} |")
    failed = [r["id"] for r in result["cases"] if not r["passed"]]
    print(f"\n{len(result['cases']) - len(failed)}/{len(result['cases'])} cases passed"
          + (f"; failing: {', '.join(failed)}" if failed else ""))


if __name__ == "__main__":
    print_table(run())
