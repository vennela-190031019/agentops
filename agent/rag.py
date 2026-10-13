"""Retriever over docs/*.md (one bullet = one chunk).

Primary: embeddings via fastembed (ONNX runtime, no PyTorch) using
sentence-transformers/all-MiniLM-L6-v2; fastembed's vectors are already
L2-normalized, so cosine similarity is a plain dot product. Model files are
cached under `.cache/fastembed/` (gitignored, restorable in CI via
actions/cache) so repeat runs don't re-download the ~90MB model.

Falls back to the original keyword+IDF retriever if fastembed or the model
can't be loaded (dependency missing, no network), so the agent keeps
working either way.
"""
import glob
import math
import os
import re

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache", "fastembed")

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


def _load_chunks(docs_dir: str) -> list[str]:
    chunks = []
    for path in sorted(glob.glob(os.path.join(docs_dir, "*.md"))):
        for line in open(path):
            line = line.strip()
            if line.startswith("- "):
                chunks.append(line[2:])
    return chunks


class _KeywordIndex:
    """Keyword retriever with IDF weighting: rare words count more than common ones."""

    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self._stems = [{_stem(t) for t in tokens(c)} for c in chunks]
        df = {}
        for st in self._stems:
            for t in st:
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(1 + len(chunks) / n) for t, n in df.items()}

    def scores(self, query: str) -> list[float]:
        """Per-chunk IDF-overlap score, same order as self.chunks, 0 if no overlap."""
        q = {_stem(t) for t in tokens(query)}
        return [sum(self._idf[t] for t in q & st) for st in self._stems]

    def search(self, query: str, top_k: int) -> list[str]:
        scored = [(s, c) for s, c in zip(self.scores(query), self.chunks) if s]
        scored.sort(key=lambda x: -x[0])  # stable: ties keep file order
        return [c for _, c in scored[:top_k]]


class _EmbeddingIndex:
    """Cosine-similarity retriever over fastembed (ONNX) MiniLM embeddings.

    Two corrections on top of raw cosine ranking, found by eval failures on
    this tiny, terse corpus:

    - MIN_SIMILARITY: pure dense retrieval never abstains -- it always
      returns the "closest" chunks even for off-topic questions. Below this
      floor nothing is relevant enough to hand to the LLM as context.
    - TIE_MARGIN: MiniLM doesn't reliably separate near-duplicate bullets
      (e.g. "refund window" scores "manager approval" fractionally above
      "within 30 days"). Candidates within TIE_MARGIN of the top cosine
      score are re-ranked by keyword overlap, then original doc order --
      the same signal the fallback keyword retriever uses.
    """

    MIN_SIMILARITY = 0.25
    TIE_MARGIN = 0.05

    def __init__(self, chunks: list[str]):
        from fastembed import TextEmbedding  # imported lazily so the fallback works without it

        self.chunks = chunks
        self._model = TextEmbedding(model_name=MODEL_NAME, cache_dir=CACHE_DIR)
        self._embeddings = list(self._model.embed(chunks)) if chunks else []
        self._keyword = _KeywordIndex(chunks)

    def search(self, query: str, top_k: int) -> list[str]:
        if not self.chunks:
            return []
        q = next(iter(self._model.query_embed(query)))
        sims = [float(q @ e) for e in self._embeddings]
        best = max(sims)
        if best < self.MIN_SIMILARITY:
            return []
        kw = self._keyword.scores(query)
        near_top = sorted(
            (i for i in range(len(self.chunks)) if best - sims[i] <= self.TIE_MARGIN),
            key=lambda i: (-kw[i], i),
        )
        far = sorted(
            (i for i in range(len(self.chunks)) if best - sims[i] > self.TIE_MARGIN),
            key=lambda i: -sims[i],
        )
        order = near_top + far
        return [self.chunks[i] for i in order[:top_k] if sims[i] >= self.MIN_SIMILARITY]


class Retriever:
    """Semantic retriever (fastembed/MiniLM), falling back to keyword+IDF."""

    def __init__(self, docs_dir=None):
        docs_dir = docs_dir or os.path.join(os.path.dirname(__file__), "..", "docs")
        self.chunks = _load_chunks(docs_dir)
        try:
            self._index = _EmbeddingIndex(self.chunks)
        except Exception:
            self._index = _KeywordIndex(self.chunks)

    def search(self, query: str, top_k: int = 2) -> list[str]:
        return self._index.search(query, top_k)
