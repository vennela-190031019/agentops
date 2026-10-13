"""Scorers. All return a float in [0, 1].

groundedness  - share of answer sentences whose content words appear in the
                retrieved context / tool output. Abstaining ("I don't have
                information") counts as grounded. Token-overlap heuristic so
                CI stays free; swap in an LLM judge for a stricter check.
tool_accuracy - 1.0 if the set of tools the agent called equals the expected set.
correctness   - 1.0 if every expected substring appears in the answer.
"""
import json
import re

from agent.llm import NO_INFO
from agent.rag import tokens

THRESHOLD = 0.6

# Wording the agent legitimately uses to report a tool's status. These phrases
# come from the tool outcome, not from the documents, so they count as grounded.
STATUS_VOCAB = {
    "denied": "you not permitted to use",
    "pending_approval": "pending human approval",
    "not_found": "couldn't find not found",
}


def _status_words(tool_results: list[dict]) -> str:
    words = []
    for r in tool_results:
        words.append(STATUS_VOCAB.get(r.get("status"), ""))
        words.append(STATUS_VOCAB.get(r.get("output", {}).get("status"), ""))
    return " ".join(words)


def groundedness(answer: str, context: list[str], tool_results: list[dict]) -> float:
    if answer.strip() == NO_INFO:
        return 1.0
    corpus = set(tokens(" ".join(context) + " " + json.dumps(tool_results) + " " + _status_words(tool_results)))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if s]
    if not sentences:
        return 0.0
    grounded = 0
    for s in sentences:
        toks = tokens(s)
        if toks and sum(t in corpus for t in toks) / len(toks) >= THRESHOLD:
            grounded += 1
    return grounded / len(sentences)


def tool_accuracy(expected: list[str], actual: list[str]) -> float:
    return 1.0 if set(expected) == set(actual) else 0.0


def correctness(answer: str, expected_contains: list[str]) -> float:
    a = answer.lower()
    return 1.0 if all(e.lower() in a for e in expected_contains) else 0.0
