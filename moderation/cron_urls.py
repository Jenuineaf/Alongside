"""Scheduled-job endpoints, mounted at `/internal/cron/`.

Its own URLconf rather than entries in `moderation/urls.py` because the whole
prefix is machine-only: nothing under `/internal/` is ever linked, and keeping
it separate means a future `robots.txt` or an edge rule can block the prefix
without touching anything a person uses.

The trailing slash matters — `.github/workflows/cron.yml` POSTs to
`<RENDER_URL>/internal/cron/stale-post-nudge/` (`deployment.md` §8).
"""

from django.urls import path

from moderation import cron_views

app_name = "cron"

urlpatterns = [
    path(
        "stale-post-nudge/",
        cron_views.stale_post_nudge_endpoint,
        name="stale_post_nudge",
    ),
]
