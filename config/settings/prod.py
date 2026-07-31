"""Production settings (Render).

Fails fast on misconfiguration. A production app that boots with a placeholder
secret key is worse than one that refuses to boot, because nobody finds out.
"""

import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
from sentry_sdk.integrations.django import DjangoIntegration

from config.settings.base import *  # noqa: F403
from config.settings.base import CLOUDINARY_URL, SECRET_KEY, env

DEBUG = False

# ── Refuse to boot on a bad config ──────────────────────────────────────────

# .env.example says production must refuse a short or placeholder key.
if len(SECRET_KEY) < 50 or "replace-me" in SECRET_KEY or SECRET_KEY.startswith("dev-"):
    raise ImproperlyConfigured(
        "SECRET_KEY looks like a development placeholder. Generate a real one: "
        'python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")

# Render's filesystem is ephemeral — uploads written to local disk vanish on the
# next deploy, silently. Better to refuse to start.
if not CLOUDINARY_URL:
    raise ImproperlyConfigured(
        "CLOUDINARY_URL must be set in production — Render's filesystem is "
        "ephemeral and uploaded media would be lost on every deploy."
    )

# ── HTTPS / security headers ────────────────────────────────────────────────

# Render terminates TLS at its proxy, so Django only sees http without this.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True

SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ── Error tracking ──────────────────────────────────────────────────────────

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        # Never ship user emails or DM bodies to a third party.
        send_default_pii=False,
    )
