# Multi-stage build: install deps with uv into a venv, then copy just the
# venv + source into a slim runtime stage. torch pulls in a lot of weight,
# so keeping the builder's package cache/toolchain out of the final image
# matters here more than in a typical small FastAPI service.

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency manifests first so this layer only rebuilds when
# dependencies actually change, not on every source edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --extra dev --no-install-project

COPY src ./src
COPY README.md ./
RUN uv sync --locked --extra dev


FROM python:3.12-slim AS runtime

# libpq for psycopg (not the [binary] wheel path in all base images) and
# curl for a cheap container-level healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Both the API service and the retrain Cloud Run Job use this exact image —
# only the container command/entrypoint differs between them (set in each
# Cloud Run service/job's own config, not baked in here):
#   API service:      uvicorn behaveguard.api:app --host 0.0.0.0 --port ${PORT:-8080}
#   Retrain job:       behaveguard run-retrain-job
# Cloud Run injects PORT; default matches local `behaveguard serve`.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn behaveguard.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
