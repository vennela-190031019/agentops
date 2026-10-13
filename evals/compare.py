"""Regression gate. Compares results.json to baseline.json.

Exit code 1 (fails CI) if any quality metric drops more than TOLERANCE, or if
any case that passed in the baseline now fails.

Usage:
  python -m evals.compare            # check
  python -m evals.compare --update   # accept current results as the new baseline
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results.json")
BASELINE = os.path.join(HERE, "baseline.json")
QUALITY = ["groundedness", "tool_accuracy", "correctness", "pass_rate"]
TOLERANCE = 0.02


def main(argv):
    res = json.load(open(RESULTS))
    if "--update" in argv:
        base = {"metrics": res["metrics"], "case_pass": {r["id"]: r["passed"] for r in res["cases"]}}
        json.dump(base, open(BASELINE, "w"), indent=2)
        print("Baseline updated.")
        return 0

    base = json.load(open(BASELINE))
    problems = []
    for m in QUALITY:
        if res["metrics"][m] < base["metrics"][m] - TOLERANCE:
            problems.append(f"{m}: {base['metrics'][m]} -> {res['metrics'][m]}")
    regressed = [r["id"] for r in res["cases"] if base["case_pass"].get(r["id"]) and not r["passed"]]
    if regressed:
        problems.append(f"{len(regressed)} regressed case(s): {', '.join(regressed)}")

    if problems:
        print("EVAL REGRESSION - failing build")
        for p in problems:
            print(" -", p)
        return 1
    print("Evals OK - no regression vs baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
