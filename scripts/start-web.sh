#!/usr/bin/env bash
# Production entrypoint (Render).
#
# Migrations run on boot. That is safe here for one specific reason: the free
# plan runs exactly one instance, so two containers can never race the same
# migration. If we ever scale past one instance, this moves to a release step.
set -euo pipefail

if [ "${RUN_MIGRATIONS_ON_START:-True}" = "True" ]; then
  echo "==> Applying migrations"
  python manage.py migrate --noinput
fi

echo "==> Starting gunicorn on 0.0.0.0:${PORT:-8000}"
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads 4 \
  --worker-class gthread \
  --timeout 60 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
