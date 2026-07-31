"""Root URL configuration.

Owned by the Architect. Feature seats add their own `<app>/urls.py` and request
an `include()` line here through Jeni — that keeps ten seats out of one file.
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
]

# Feature seats plug in here, one line each, as their phase lands:
#   path("", include("posts.urls")),            # Posts & Feed — landing, feed, post detail
#   path("u/", include("accounts.urls")),       # Accounts — profiles, settings, follow, block
#   path("search/", include("discovery.urls")), # Discovery — search, filters, Home
#   path("messages/", include("messaging.urls")),
#   path("notifications/", include("notifications.urls")),
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
