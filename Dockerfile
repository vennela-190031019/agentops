# API image: FastAPI backend + LangGraph agent.
#
# The fastembed model is downloaded at build time (not first request) so a
# fresh container serves its first /chat request without a multi-second
# cold-start model fetch. Runs as a non-root user; SQLite data (traces,
# pending approvals, LangGraph checkpoints) is expected to live on a mounted
# volume at /app/data (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENTOPS_DB_PATH=/app/data/agentops.db \
    AGENTOPS_CHECKPOINT_DB=/app/data/agentops_checkpoints.db

WORKDIR /app

RUN groupadd --system appuser && useradd --system --gid appuser --home-dir /app appuser

COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-download the fastembed/MiniLM ONNX model into the same cache dir
# agent/rag.py uses at runtime (<repo root>/.cache/fastembed), so container
# startup never has to hit the network.
RUN python -c "\
from fastembed import TextEmbedding; \
TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2', cache_dir='.cache/fastembed')"

COPY agent/ agent/
COPY api/ api/
COPY guardrails/ guardrails/
COPY tracing/ tracing/
COPY evals/ evals/
COPY docs/ docs/

RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
