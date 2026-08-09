# Production-oriented backend image.
# Dependencies are installed in a separate layer from application code so that
# source edits do not invalidate the (slow) dependency layer.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- dependency layer -------------------------------------------------------
FROM base AS deps
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# --- development ------------------------------------------------------------
FROM deps AS development
RUN pip install ".[dev]"
COPY . .
RUN pip install --no-deps -e .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- production -------------------------------------------------------------
FROM deps AS production
COPY app ./app
COPY pyproject.toml ./
RUN pip install --no-deps . \
    && adduser --disabled-password --gecos "" --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
