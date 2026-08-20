"""Local development and CI settings."""

import socket
from urllib.parse import urlparse

from config.settings.base import *  # noqa: F403
from config.settings.base import (  # noqa: F401
    BASE_DIR,
    CACHES,
    INSTALLED_APPS,
    MIDDLEWARE,
    REDIS_URL,
    env,
)

DEBUG = env.bool("DEBUG", default=True)

# Dev only — prod.py never widens this.
ALLOWED_HOSTS = ["*"]

# django-debug-toolbar. Skipped under pytest: the toolbar wraps every response
# and inflates query counts, which would break QA's N+1 budget tests
# (testing.md §5.4).
import sys  # noqa: E402

RUNNING_TESTS = "pytest" in sys.modules or "test" in sys.argv

if DEBUG and not RUNNING_TESTS:
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
    INTERNAL_IPS = ["127.0.0.1", "localhost"]
    # Inside Docker the client IP is the gateway, not 127.0.0.1, so the usual
    # INTERNAL_IPS check never matches. Show the toolbar whenever DEBUG is on.
    DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda request: True}

# ── Cache: fall back to local memory when Redis isn't running ───────────────
#
# The block set is cached in Redis (ADR-0003), and `blocked_user_ids()` runs on
# effectively every authenticated request. With `RedisCache` configured and no
# Redis listening, that is a `ConnectionError` on every signed-in page — so
# `git clone && manage.py runserver` gives a new developer a 500 on the whole
# logged-in half of the product, for a reason the traceback does not make
# obvious.
#
# Docker Compose still provides the real thing, and this is dev-only: prod.py
# does not import it. Local memory is a correct cache backend here, just
# per-process, which is exactly right for one runserver.


def _redis_is_reachable(url: str, timeout: float = 0.35) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 6379), timeout):
            return True
    except OSError:
        return False


if not _redis_is_reachable(REDIS_URL):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "alongside-dev",
        }
    }
    # Celery would queue tasks nobody is going to consume, so run them inline —
    # which is also what production does on Render's free tier
    # (deployment.md §4), so this matches prod rather than diverging from it.
    CELERY_TASK_ALWAYS_EAGER = True

# Emails print to the console by default — see .env.example.
