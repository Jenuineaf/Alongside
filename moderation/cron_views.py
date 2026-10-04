"""The doorway for scheduled jobs. `deployment.md` §4 and §8.

Render's free tier has no always-on background worker, and a Celery Beat
process inside the free web service would be asleep most of the time — the
service spins down after 15 minutes idle, so the nightly nudge would silently
never fire. So GitHub Actions cron POSTs here on a schedule, and the request
itself wakes the app.

**This module is the doorway, not the job.** The nudge logic is
`moderation/tasks.py`; everything here is authentication and plumbing, which is
how `deployment.md` §8 scoped it.
"""

import hmac

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from moderation.tasks import stale_post_nudge

# What `.github/workflows/cron.yml` sends.
CRON_HEADER = "X-Cron-Key"


@csrf_exempt
@require_POST
def stale_post_nudge_endpoint(request):
    """Run the nudge job. POST only, shared-secret header, JSON back.

    `csrf_exempt` because the caller is GitHub Actions with no session and no
    cookie to carry a token — the shared secret is the authentication, and CSRF
    protects session-authenticated browsers, which this endpoint has none of.

    **404, not 403, on a bad key.** A 403 confirms the endpoint exists and that
    the key was merely wrong, which is a free oracle for anybody probing
    `/internal/`. A 404 says nothing.
    """
    if not _authorised(request):
        raise Http404("No such endpoint.")

    result = stale_post_nudge.delay()

    # `CELERY_TASK_ALWAYS_EAGER` is True in production on the free tier
    # (deployment.md §4), so `.delay()` has already run the job inline by the
    # time we get here and `result.get()` is free. Under a real worker it would
    # block, so the counts are reported only when they are already known —
    # the cron workflow checks the status code, not the body.
    payload = {"job": "stale-post-nudge", "queued": True}
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        payload.update(result.get(), queued=False)

    return JsonResponse(payload)


def _authorised(request) -> bool:
    """Constant-time compare against `CRON_SECRET`.

    `hmac.compare_digest`, not `==`: a plain comparison short-circuits on the
    first differing byte, which leaks the secret one character at a time to
    anybody willing to time a few thousand requests.

    An unset `CRON_SECRET` refuses everything rather than allowing everything —
    the failure mode of a misconfigured deploy should be a job that does not
    run, not an open endpoint.
    """
    expected = getattr(settings, "CRON_SECRET", "")
    if not expected:
        return False

    provided = request.headers.get(CRON_HEADER, "")
    return hmac.compare_digest(provided, expected)
