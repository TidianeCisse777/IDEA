FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# HuggingFace cache dans /app/models (monté en volume)
ENV HF_HOME=/app/models
ENV TRANSFORMERS_CACHE=/app/models

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

COPY . .

# Fail the image build if the offline Natural Earth bundle is incomplete.
RUN python -c "from core.cartography import configure_offline_cartopy; configure_offline_cartopy()"

# Bake the copepod RAG index (chroma_db) into the image so a fresh clone
# never has to build it. The `.dockerignore` intentionally does NOT skip
# `core/copepod_rag/chroma_db`, and docker-compose keeps this path on a
# named volume (see `copepod_rag_index`) so the host `.:/app` bind mount
# does not shadow the baked index at runtime.
RUN python core/copepod_rag/build_index.py

EXPOSE 8000

CMD ["python", "serve.py"]
