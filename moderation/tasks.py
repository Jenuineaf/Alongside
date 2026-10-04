"""The stale-post nudge — the job that keeps the feed honest.

Spec §4.8 calls mismatched expectations the #1 killer in this category, and
`is_stale` is the countermeasure: a post nobody has touched in a month is
quietly demoted rather than hidden, and its author gets one chance to say "yes,
still looking" first.

**The state machine (TS-10), written down because three fields with no rules is
what the Trust & Safety review found:**

| From | When | Effect |
|---|---|---|
| fresh (`is_stale=False`, `nudged_at=NULL`) | no activity for `NUDGE_AFTER`, still `looking`, not deleted | send a `stale_nudge`, set `nudged_at=now` |
| nudged | no activity for `DEMOTE_AFTER` past `nudged_at` | `is_stale=True` |
| nudged **or** stale | any `last_activity_at` bump | `is_stale=False`, `nudged_at=NULL` |

The third row is not this module's work — it is `Post.touch_activity()`, called
on comment and on author edit, and it is why nothing here ever has to un-stale a
post.

**The job never touches `status`.** Q4 settled that `is_stale` (the system's
judgement) and `status` (the author's choice) are separate fields precisely so
the system cannot overwrite what the author said. A job that "helpfully" closed
a stale post would be the whole reason that decision exists, undone.

**Sparks do not count as activity** (TS-6). `last_activity_at` is bumped by
author edit, new comment, and the author's own "yes, still looking" — not by a
stranger's one click, or any passer-by could keep a dead post alive forever.

Production runs this through a GitHub Actions cron hitting
`/internal/cron/stale-post-nudge/`, not Celery Beat: Render's free tier has no
always-on worker and a beat process inside the web service would be asleep most
of the time, silently missing its schedule (`deployment.md` §4). With
`CELERY_TASK_ALWAYS_EAGER=True` there, `.delay()` runs inline in that request —
which is fine for a job this size, and is why the task is written to be cheap
and idempotent rather than to stream.
"""

from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from posts.models import Post, PostStatus

# The Trust & Safety seat's proposal in `docs/review/trust-safety.md` (TS-8/TS-9)
# — 30 days quiet earns a nudge, 7 more days of silence earns the demotion.
# **Not yet ruled on by Jeni**, which is why they are named constants with this
# comment attached rather than numbers inline: changing the policy should be a
# one-line edit, not a hunt.
NUDGE_AFTER = timedelta(days=30)
DEMOTE_AFTER = timedelta(days=7)

# A ceiling per run, so one neglected month cannot turn into a job that walks
# the whole table inside a single cron request on a free-tier box. The leftovers
# are picked up tomorrow; nothing is lost, because the query is a predicate over
# current state rather than a queue being drained.
MAX_PER_RUN = 500


@shared_task(name="moderation.stale_post_nudge")
def stale_post_nudge() -> dict:
    """Run both halves of the state machine. Returns what it did, for the cron log.

    Order matters: nudge first, then demote. Reversed, a post that crossed both
    thresholds between two runs — which is every post, the first time this job
    runs against a seeded database — would be demoted without ever having been
    asked, and the nudge is the entire point of the feature.
    """
    nudged = send_nudges()
    demoted = demote_unanswered()
    return {"nudged": nudged, "demoted": demoted}


@transaction.atomic
def send_nudges() -> int:
    """Ask the authors of quiet posts whether they are still looking.

    `post_stale_candidates_idx` is partial on exactly this predicate (TS-11), so
    this is an index scan rather than a walk of every post in the table.
    """
    cutoff = timezone.now() - NUDGE_AFTER

    candidates = list(
        Post.objects.filter(
            status=PostStatus.LOOKING,
            is_stale=False,
            nudged_at__isnull=True,
            last_activity_at__lt=cutoff,
        ).select_related("author")[:MAX_PER_RUN]
    )
    if not candidates:
        return 0

    from notifications import services as notification_services

    for post in candidates:
        notification_services.notify_stale_nudge(post)

    # One UPDATE for the whole batch, and it is what makes the job idempotent:
    # `nudged_at` is the guard the candidate query filters on, so a second run
    # in the same hour finds nothing to do rather than nudging everybody twice.
    Post.objects.filter(pk__in=[post.pk for post in candidates]).update(
        nudged_at=timezone.now()
    )
    return len(candidates)


@transaction.atomic
def demote_unanswered() -> int:
    """Demote the posts whose authors did not answer the nudge.

    `is_stale` **ranks lower, never hides** (Q4). The post stays in the feed and
    stays findable in search; it simply stops outranking ideas somebody is
    actually still working on. Hiding it would be the system overruling the
    author, which is the line this feature does not cross.

    `nudged_at` is deliberately left set. It is the record that the author was
    asked, and clearing it here would restart the cycle and nudge them again in
    thirty days about a post they have already ignored once.
    """
    cutoff = timezone.now() - DEMOTE_AFTER

    return Post.objects.filter(
        status=PostStatus.LOOKING,
        is_stale=False,
        nudged_at__isnull=False,
        nudged_at__lt=cutoff,
        # Guards the case where the author replied *to the nudge* without
        # touching the post: `touch_activity()` clears `nudged_at`, so this
        # should never match a revived post — but the day it does, the right
        # answer is to leave it alone rather than demote something with recent
        # activity.
        last_activity_at__lt=F("nudged_at"),
    ).update(is_stale=True)
