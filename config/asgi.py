"""ASGI entrypoint.

Unused today — production runs gunicorn/WSGI. This becomes the entrypoint when
Django Channels lands in Phase 5 and the app server switches to Uvicorn/Daphne
(tech-stack.md §4, deployment.md §9). Kept in place from day one so that switch
is a config change rather than a new file.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
