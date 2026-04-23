# =============================================================
# Backend-only Dockerfile (uses uv)
# Build from backend/: docker build -t model-link-backend .
# =============================================================
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Python dependencies (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY . .

# Install the project itself
RUN uv sync --frozen --no-dev

# Expose the port
EXPOSE 8000

# Run with uvicorn — Quart app is native ASGI
CMD ["uv", "run", "uvicorn", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--timeout-keep-alive", "1200", "app.main:app"]
