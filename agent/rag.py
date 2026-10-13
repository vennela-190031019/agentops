"""Tiny keyword retriever over docs/*.md (one bullet = one chunk).

Dependency-free so CI is fast and deterministic. Swap for Chroma +
sentence-transformers later behind the same `search` interface.
"""
import glob
import math
import os
import re

STOP = {
    "the", "a", "an", "is", "are", "do", "does", "i", "my", "me", "you", "your",
    "to", "of", "in", "on", "for", "and", "or", "how", "what", "can", "it",
    "we", "if", "be", "by", "from", "with", "at", "this", "that", "long",
    "much", "who", "when", "have", "get", "not", "take", "takes",
}


def tokens(text: str):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "s"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)]
    return t


class Retriever:
    """Keyword retriever with IDF weighting: rare words count more than common ones."""

    def __init__(self, docs_dir=None):
        docs_dir = docs_dir or os.path.join(os.path.dirname(__file__), "..", "docs")
        self.chunks = []
        for path in sorted(glob.glob(os.path.join(docs_dir, "*.md"))):
            for line in open(path):
                line = line.strip()
                if line.startswith("- "):
                    self.chunks.append(line[2:])
        self._stems = [{_stem(t) for t in tokens(c)} for c in self.chunks]
        df = {}
        for st in self._stems:
            for t in st:
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(1 + len(self.chunks) / n) for t, n in df.items()}

    def search(self, query: str, top_k: int = 2):
        q = {_stem(t) for t in tokens(query)}
        scored = []
        for chunk, st in zip(self.chunks, self._stems):
            score = sum(self._idf[t] for t in q & st)
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda x: -x[0])  # stable: ties keep file order
        return [c for _, c in scored[:top_k]]
