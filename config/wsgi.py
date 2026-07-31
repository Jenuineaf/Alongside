"""WSGI entrypoint — `gunicorn config.wsgi:application` (scripts/start-web.sh)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
