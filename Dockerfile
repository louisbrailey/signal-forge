# Signal Forge — research / paper-trading only. No brokerage connector is built in.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal; psycopg[binary] needs no build toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
RUN pip install ".[postgres,llm]"

# Runtime state lives on a mounted volume, never in the image.
RUN mkdir -p /data /secrets
ENV SIGNALFORGE_DATA_DIR=/data

# Drop privileges.
RUN useradd --system --home /app --uid 10001 signalforge \
    && chown -R signalforge /app /data /secrets
USER signalforge

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "signalforge.app.main:app", "--host", "0.0.0.0", "--port", "8787"]
