"""Local development and CI settings."""

from config.settings.base import *  # noqa: F403
from config.settings.base import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, env  # noqa: F401

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

# Emails print to the console by default — see .env.example.
