#!/usr/bin/env bash
# Local dev entrypoint for the `web` service.
# Compose healthchecks already guarantee Postgres and Redis are up, so this
# only has to migrate and serve.
set -euo pipefail

echo "==> Applying migrations"
python manage.py migrate --noinput

echo "==> Starting development server on 0.0.0.0:8000"
exec python manage.py runserver 0.0.0.0:8000
