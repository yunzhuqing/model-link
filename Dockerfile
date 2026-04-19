# =============================================================
# Multi-stage Dockerfile: React frontend + Flask backend
# Build from monorepo root: docker build -t model-link .
# Uses uv for fast Python dependency management.
# =============================================================

# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Install dependencies first (cache layer)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build the React app
COPY frontend/ .
RUN npm run build


# Stage 2: Python backend + React static files
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
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy backend application code
COPY backend/ .

# Install the project itself
RUN uv sync --frozen --no-dev

# Copy React build output into static/ folder (Flask will serve it)
COPY --from=frontend-build /app/frontend/dist ./static

# Expose the port
EXPOSE 8000

# Run with uvicorn (use uv run to ensure venv is activated)
CMD ["uv", "run", "uvicorn", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--timeout-keep-alive", "1200", "app.main:asgi_app"]
