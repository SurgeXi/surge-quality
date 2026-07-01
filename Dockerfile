# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
# Multi-stage build: surge-quality recommender service
# Stage 1: build wheels
FROM python:3.12-slim AS builder

WORKDIR /build

# Build deps for psycopg2-binary + cryptography wheels (most ship as binary; libpq + gcc kept as safety)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip wheel \
 && pip wheel --no-cache-dir --wheel-dir /build/wheels -e .

# Stage 2: slim runtime
FROM python:3.12-slim

ARG APP_USER=surge_quality
ARG APP_UID=10310

RUN groupadd --system --gid ${APP_UID} ${APP_USER} \
 && useradd  --system --uid ${APP_UID} --gid ${APP_UID} \
             --home-dir /opt/surge-quality --shell /usr/sbin/nologin ${APP_USER} \
 && mkdir -p /opt/surge-quality /var/lib/surge-quality \
 && chown -R ${APP_USER}:${APP_USER} /opt/surge-quality /var/lib/surge-quality

# libpq for psycopg2 runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/surge-quality

COPY --from=builder /build/wheels /tmp/wheels
COPY pyproject.toml ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels surge-quality \
 && rm -rf /tmp/wheels

USER ${APP_USER}

EXPOSE 9310

# /healthz is the liveness probe; /readyz is the readiness probe (checks DB + token config)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:9310/healthz',timeout=3); sys.exit(0 if r.status==200 else 1)" || exit 1

CMD ["uvicorn", "surge_quality.main:app", "--host", "0.0.0.0", "--port", "9310", "--workers", "2"]
