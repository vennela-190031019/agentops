"""Prompt-injection detection: regex/heuristics only, no paid APIs or models."""
import re

REFUSAL_MESSAGE = "I can't help with that request."

_PATTERNS = [
    (re.compile(r"\b(ignore|disregard|forget|override)\b[^.?!\n]{0,40}\b"
                r"(previous|prior|above|earlier|before|told|said|instructed|given|your)\b",
                re.I), "override/ignore previous instructions"),
    (re.compile(r"\b(reveal|show|print|output|repeat|leak)\b[^.?!\n]{0,30}\byour\b"
                r"[^.?!\n]{0,20}\b(system\s+prompt|hidden|secret|original|underlying|"
                r"prompt|rules?|instructions?|guidelines?)\b", re.I),
     "requests system prompt / hidden rules"),
    (re.compile(r"\byou\s+are\s+now\s+[a-z0-9 _'\"-]+", re.I), "role override (\"you are now ...\")"),
    (re.compile(r"act\s+as\s+(if\s+you\s*('re|\s+are)\s+)?(an?\s+)?"
                r"(unrestricted|unfiltered|jailbroken)\b", re.I), "jailbreak persona request"),
    (re.compile(r"\bdeveloper\s+mode\b", re.I), "developer mode jailbreak"),
    (re.compile(r"\bdo\s+anything\s+now\b|\bDAN\b"), "DAN jailbreak"),
    (re.compile(r"override\s+(your\s+)?(safety|guardrails?|rules)", re.I), "override safety/guardrails"),
    (re.compile(r"\bsystem\s*:\s*\S", re.I), "fake system-role injection"),
    (re.compile(r"new\s+instructions?\s*:\s*\S", re.I), "injected new instructions"),
]


def detect_injection(text: str) -> tuple[bool, str | None]:
    """Return (flagged, reason). reason is the matched heuristic's label, or None."""
    if not text:
        return False, None
    for pattern, reason in _PATTERNS:
        if pattern.search(text):
            return True, reason
    return False, None
