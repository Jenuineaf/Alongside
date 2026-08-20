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
    # Last: owns "" (landing) and would otherwise shadow the prefixes above.
    path("", include("posts.urls")),
]

# Still to land with their phases:
#   path("report/", include("moderation.urls")),
#   path("internal/cron/", include("moderation.cron_urls")),  # deployment.md §4
#   path("api/", include("config.api_urls")),   # DRF — tech-stack.md §0

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    try:
        import debug_toolbar  # noqa: F401

        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
    except ImportError:
        # Not installed under pytest — see config/settings/dev.py.
        pass
