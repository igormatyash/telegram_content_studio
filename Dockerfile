FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY voicerhub_bot ./voicerhub_bot
COPY scripts ./scripts
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/generated \
    && chown -R appuser:appuser /app

USER appuser
