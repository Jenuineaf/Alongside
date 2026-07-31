"""Project-level views. Deliberately tiny — feature views belong to their seats."""

from django.http import HttpResponse


def healthz(request):
    """Liveness probe for Render (`render.yaml` healthCheckPath).

    **This must never touch the database or Redis.** Render restarts the service
    when the health check fails, so a health check that queries Postgres turns a
    brief Neon blip into a restart loop that takes the site down for longer than
    the blip would have. `deployment.md` §8 asks for exactly this behaviour, and
    QA has a test for it (`testing.md` §11.2).
    """
    return HttpResponse("ok", content_type="text/plain")
