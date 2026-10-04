"""Root URL configuration.

One `include()` per app. `posts.urls` is mounted last because it owns `""`,
and a catch-all prefix in front of the named ones would shadow them.

`discovery`, `messaging` and `notifications` are wired as **name-only stubs**:
their views exist but render templates that do not, so visiting them 500s until
their phase lands. They are included anyway because `components/_tab_bar.html`
and `_app_bar.html` reverse those names on every authenticated page — without
the includes, every signed-in screen dies with `NoReverseMatch` instead.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    # Liveness probe for render.yaml and the deploy checks. Deliberately does
    # not touch the database — see config/views.py.
    path("healthz/", healthz, name="healthz"),
    # django-allauth: signup, login, logout, password reset, Google.
    path("accounts/", include("allauth.urls")),
    # Accounts — profiles, settings, follow, block. `/u/<username>/` is the
    # public profile URL the username validator's reserved list protects.
    path("u/", include("accounts.urls")),
    path("search/", include("discovery.urls")),
    path("messages/", include("messaging.urls")),
    path("notifications/", include("notifications.urls")),
    path("s/", include("social.urls")),
    # Reporting. Moderation itself is Django admin (§6.1) — there is no review
    # UI to route here.
    path("report/", include("moderation.urls")),
    # Scheduled jobs, machine-only. GitHub Actions cron POSTs here with a
    # shared secret because Render's free tier has no always-on worker to run
    # Celery Beat (deployment.md §4).
    path("internal/cron/", include("moderation.cron_urls")),
    # Last: owns "" (landing) and would otherwise shadow the prefixes above.
    path("", include("posts.urls")),
]

# django-ratelimit raises `Ratelimited`, which is a 403 by default — misleading
# for a limit that will lift on its own in an hour. 429 says "later", which is
# both true and what a client can act on.
handler403 = "config.views.permission_denied"

# Still to land with its phase:
#   path("api/", include("config.api_urls"))   # DRF — tech-stack.md §0

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    try:
        import debug_toolbar  # noqa: F401

        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
    except ImportError:
        # Not installed under pytest — see config/settings/dev.py.
        pass
