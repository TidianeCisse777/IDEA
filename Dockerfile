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
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

COPY . .

EXPOSE 8000

CMD ["python", "serve.py"]
