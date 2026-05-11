# Upstream LiteLLM images (same registry/tags for both names):
#   - litellm             — general proxy image
#   - litellm-database    — proxy built for Postgres-backed mode (virtual keys, spend, Prisma/UI tooling
#                           pre-baked per upstream). This is NOT a Postgres server; you still set
#                           DATABASE_URL / LITELLM_DATABASE_URL to Azure Postgres (or similar).
#
# You run one container from one base image — not "litellm + litellm-database" as two services.
#
# Local build examples:
#   docker build -t idea-litellm:local .
#   docker build --build-arg LITELLM_IMAGE=litellm --build-arg LITELLM_VERSION=v1.83.7-stable -t idea-litellm:local .
#
# https://docs.litellm.ai/docs/proxy/deploy — "Deploy with Database" recommends the litellm-database image.
ARG LITELLM_IMAGE=litellm-database
ARG LITELLM_VERSION=v1.83.7-stable

FROM ghcr.io/berriai/${LITELLM_IMAGE}:${LITELLM_VERSION}

# ARG is not inherited past FROM; re-declare for LABEL expansion.
ARG LITELLM_IMAGE
ARG LITELLM_VERSION

WORKDIR /app

COPY litellm_config.yaml .

# Log level (replaces deprecated litellm_settings.set_verbose). Override per env: DEBUG, INFO, ERROR.
ENV LITELLM_LOG=INFO

LABEL litellm.upstream-image="ghcr.io/berriai/${LITELLM_IMAGE}"
LABEL litellm.upstream-tag="${LITELLM_VERSION}"

EXPOSE 8080

# Liveness only — does not hit Azure/Databricks models (no probe-driven LLM spend).
# Tune start-period if cold starts (DB, workers) exceed this window on App Service.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/liveliness', timeout=4)" || exit 1

CMD ["--port", "8080", "--config", "litellm_config.yaml"]
