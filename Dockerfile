FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

# Cache dependency layer without dev packages
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Install project package into the venv and clean leftover caches
COPY src ./src
COPY README.md ./
RUN uv sync --locked --no-dev \
    && find /app/.venv -type d -name "__pycache__" -exec rm -rf {} + \
    && find /app/.venv -type d -name "tests" -exec rm -rf {} +


FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["sh", "-c", "uvicorn behaveguard.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
