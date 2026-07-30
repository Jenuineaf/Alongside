# syntax=docker/dockerfile:1
#
# Buildmates — one Dockerfile, two targets.
#   dev  → used by docker-compose (all five services share this image)
#   prod → used by Render (the final stage, so a plain `docker build` gets it)

# ─────────────────────────────────────────────────────────────
# base — shared layers
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the compose healthcheck; libpq/build-essential cover any
# dependency that has no wheel for slim. Trim these once CI proves them unused.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements alone first so dependency layers cache across code edits.
COPY requirements/ requirements/
RUN pip install --upgrade pip && pip install -r requirements/base.txt

# ─────────────────────────────────────────────────────────────
# dev — runserver, hot reload, test tooling
# ─────────────────────────────────────────────────────────────
FROM base AS dev

RUN pip install -r requirements/dev.txt

# Source is bind-mounted by docker-compose, so this COPY only matters if the
# dev image is run without the mount.
COPY . .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ─────────────────────────────────────────────────────────────
# prod — gunicorn, WhiteNoise, non-root
# ─────────────────────────────────────────────────────────────
FROM base AS prod

RUN pip install -r requirements/prod.txt

COPY . .

# Bake static files into the image so boot is fast and WhiteNoise has something
# to serve. collectstatic never touches the database, so throwaway values for
# the required env vars are safe here — none of them survive into the runtime
# environment (Render injects the real ones).
RUN SECRET_KEY="collectstatic-build-placeholder-not-used-at-runtime-000000000" \
    DATABASE_URL="postgres://build:build@127.0.0.1:5432/build" \
    REDIS_URL="redis://127.0.0.1:6379/0" \
    ALLOWED_HOSTS="localhost" \
    DEBUG="False" \
    DJANGO_SETTINGS_MODULE="config.settings.prod" \
    python manage.py collectstatic --noinput

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000
EXPOSE 8000

CMD ["/app/scripts/start-web.sh"]
