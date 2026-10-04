"""Project-level views. Deliberately tiny — feature views belong to their seats."""

from django.http import HttpResponse
from django.shortcuts import render


def healthz(request):
    """Liveness probe for Render (`render.yaml` healthCheckPath).

    **This must never touch the database or Redis.** Render restarts the service
    when the health check fails, so a health check that queries Postgres turns a
    brief Neon blip into a restart loop that takes the site down for longer than
    the blip would have. `deployment.md` §8 asks for exactly this behaviour, and
    QA has a test for it (`testing.md` §11.2).
    """
    return HttpResponse("ok", content_type="text/plain")


def permission_denied(request, exception=None):
    """`handler403`, which is also where a rate limit lands.

    django-ratelimit raises `Ratelimited`, a subclass of `PermissionDenied`, so
    Django routes it here. A plain 403 is the wrong answer for it: 403 means
    "not allowed", and this is "not allowed *yet*" — the limit lifts on its own
    within the hour. **429 with a Retry-After** says that, and is the only form
    of it a client can act on.

    A genuine permission denial still gets 403. The two are told apart by the
    exception type rather than by the view, because every rate-limited view in
    the project would otherwise have to remember to translate it.
    """
    from django_ratelimit.exceptions import Ratelimited

    if isinstance(exception, Ratelimited):
        response = render(request, "429.html", status=429)
        # An hour, because every rate in `moderation/limits.py` is per hour.
        # Without this a client has no idea whether to retry in a second or a
        # day, and the polite ones hammer.
        response["Retry-After"] = "3600"
        return response

    return render(request, "403.html", status=403)
