"""Shared settings for every environment.

Owned by the Architect. Other seats request changes through Jeni — this file is
imported by dev.py and prod.py, so a mistake here breaks all five services at
once.

Everything environment-specific is read through django-environ (`tech-stack.md`
§8): no secrets in code, ever. Variable names match `.env.example` exactly.
"""

from pathlib import Path

import environ

# config/settings/base.py → config/settings → config → repo root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Read .env if present. In Docker and on Render the variables are already in the
# environment, so this is a no-op there rather than a requirement.
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))

# ── Core ────────────────────────────────────────────────────────────────────

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Django 5.2 default. Stated explicitly because data-model.md §0 depends on it.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Applications ────────────────────────────────────────────────────────────

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # Required by allauth (data-model.md §10 step 2).
    "django.contrib.sites",
    "django.contrib.staticfiles",
    # Postgres-only field and index types: ArrayField, SearchVectorField,
    # GinIndex, TrigramExtension. tech-stack.md §2.
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "crispy_forms",
    "crispy_tailwind",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "cloudinary",
    "cloudinary_storage",
]

# One Django app per bounded area — tech-stack.md §13.
# Only `accounts` has models today; the rest are registered now so migrations
# land in the right package from the first commit rather than being moved later.
LOCAL_APPS = [
    "accounts",
    "posts",
    "discovery",
    "social",
    "messaging",
    "notifications",
    "moderation",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

SITE_ID = 1

# ── Middleware ──────────────────────────────────────────────────────────────

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Directly after SecurityMiddleware, per WhiteNoise's docs.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # allauth 65 requires this and fails loudly at request time without it.
    "allauth.account.middleware.AccountMiddleware",
]

# ── Templates ───────────────────────────────────────────────────────────────

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Puts `unread_alerts` (an int) in the context of every template so
                # the bell badge in `components/_tab_bar.html` renders on every
                # authenticated page. The Architect owns this line; the **Builder
                # seat owns `notifications/context_processors.py` itself** — the
                # contract is a callable `unread_alerts(request)` returning
                # `{"unread_alerts": int}`.
                "notifications.context_processors.unread_alerts",
            ],
        },
    },
]

CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

# ── Database ────────────────────────────────────────────────────────────────

# PostgreSQL only. Never SQLite — SearchVectorField, ArrayField, GinIndex,
# partial indexes and pg_trgm either don't exist or silently no-op on it
# (tech-stack.md §1, testing.md §1 rule 2).
DATABASES = {
    "default": env.db("DATABASE_URL"),
}
# Reuse connections rather than reconnecting per request. Matters on Neon,
# where every connection crosses the internet.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

# ── Authentication ──────────────────────────────────────────────────────────

# The single most important line in this file. Must be set before the first
# migration runs — roadmap.md ground rule 2, data-model.md §10.
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_UNIQUE_EMAIL = True

# Without these four lines allauth uses its own adapter and forms, and everything
# in accounts/adapters.py and accounts/forms.py is dead code: usernames derived
# from Google go back to failing the [a-z0-9_]{3,30} validator (data-model.md
# §10) and `display_name` is never collected at signup.
ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "accounts.adapters.SocialAccountAdapter"
ACCOUNT_FORMS = {"signup": "accounts.forms.SignupForm"}
SOCIALACCOUNT_FORMS = {"signup": "accounts.forms.SocialSignupForm"}

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}

# ── Internationalization ────────────────────────────────────────────────────

LANGUAGE_CODE = "en-us"
# Store UTC, render in the viewer's locale — data-model.md §0.
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ── Static & media ──────────────────────────────────────────────────────────

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

CLOUDINARY_URL = env("CLOUDINARY_URL", default="")

STORAGES = {
    # Cloudinary when configured; local disk otherwise so the app runs without
    # credentials. Render's filesystem is ephemeral, so prod must set it
    # (tech-stack.md §7) — prod.py enforces that.
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if CLOUDINARY_URL
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ── Caching & Celery ────────────────────────────────────────────────────────

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Shared secret for the GitHub Actions cron endpoint that stands in for Celery
# Beat in production — deployment.md §4.
CRON_SECRET = env("CRON_SECRET", default="")

# ── Email ───────────────────────────────────────────────────────────────────

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Alongside <noreply@alongside.app>")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

# ── DRF ─────────────────────────────────────────────────────────────────────

# A small, documented JSON API over posts and search — tech-stack.md §0.
# Public read access is non-negotiable (CLAUDE.md rule 7), so the default
# permission is read-only-for-anonymous rather than authenticated-only.
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# ── Logging ─────────────────────────────────────────────────────────────────

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}
