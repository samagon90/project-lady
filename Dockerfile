# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg для конвертации аудио в OGG/Opus
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Piper (локальный TTS) — официальный релиз, бесплатный
ARG PIPER_VERSION=1.2.0
RUN curl -fL -o /tmp/piper.tar.gz \
        "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_amd64.tar.gz" \
    && tar -xzf /tmp/piper.tar.gz -C /opt \
    && ln -s /opt/piper/piper /usr/local/bin/piper \
    && rm /tmp/piper.tar.gz

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY workflows ./workflows
COPY prompts ./prompts

RUN pip install .

# Данные, БД, голосовые модели (смонтировать volume)
RUN mkdir -p /app/data /app/models
VOLUME ["/app/data", "/app/models"]

CMD ["python", "-m", "src.main"]
