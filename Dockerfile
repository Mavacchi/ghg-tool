# GHG Tool — Application Dockerfile
#
# Multi-stage build:
#   builder  — installs all dependencies (including dev extras for compilation checks)
#   runtime  — slim image with only runtime deps + wheel
#
# Per architecture.md §14: Python 3.11-slim base, non-root user, no OS packages
# installed beyond what is strictly needed by psycopg and weasyprint.
#
# Usage:
#   docker build -t ghg-tool:dev .
#   docker run --rm -e SQLALCHEMY_URL=postgresql+psycopg://... ghg-tool:dev

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools only (removed in runtime stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first to leverage Docker layer cache
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheel; pip install into /install prefix for easy COPY into runtime
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir .

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="data-engineer-agent" \
      description="GHG Accounting Tool — CSRD ESRS E1 + EU ETS Phase IV" \
      version="0.1.0"

# Runtime system dependencies:
#   - libpq5, libssl3, libffi8: asyncpg / psycopg
#   - libcairo2 + libpango* + libgdk-pixbuf + libharfbuzz + shared-mime-info +
#     fonts-liberation: WeasyPrint PDF rendering (closes the gap that would
#     otherwise make POST /api/v1/exports/pdf fail at runtime)
# Kept to minimum; no dev/build tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libssl3 \
        libffi8 \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libharfbuzz0b \
        shared-mime-info \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (NFR-21 security)
RUN groupadd -r ghg && useradd -r -g ghg -d /app -s /sbin/nologin ghg

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source (wheel already installed; this is for alembic migrations access)
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

# Copy data directories (read-only at runtime)
COPY data/ ./data/

# Streamlit theme config — read at runtime from the CWD's .streamlit/ dir.
# Carries the Gresmalt chrome palette; absent ➜ Streamlit falls back to
# its default theme, the app still works.
COPY .streamlit/ ./.streamlit/

# Operational scripts (seed_demo_data, create_user). Not bundled in the
# wheel because they are admin-side CLI tools, but the API container
# imports `scripts.seed_demo_data` from its lifespan hook to auto-seed
# demo data on first launch when GHG_DEMO_MODE=true.
COPY scripts/ ./scripts/
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Ensure non-root ownership
RUN chown -R ghg:ghg /app

USER ghg

# Environment defaults (override at runtime via --env-file or -e flags)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SQLALCHEMY_URL="" \
    GHG_LOG_LEVEL="INFO"

# Default command: run alembic upgrade to head then start uvicorn
# Override CMD in docker-compose for ETL or migration-only runs.
CMD ["python", "-m", "uvicorn", "ghg_tool.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
