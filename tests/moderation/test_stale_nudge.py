"""The stale-post nudge — the anti-ghosting job, and its state machine.

Spec §4.8 calls ghosting the #1 killer in this category. `is_stale` is the
countermeasure and, as the Trust & Safety review put it, it arrived as "three
fields and zero rules". These are the rules (TS-10):

| From | When | Effect |
|---|---|---|
| fresh | quiet for 30 days, still looking | nudge, set `nudged_at` |
| nudged | 7 more days of silence | `is_stale=True` |
| nudged or stale | any activity bump | `is_stale=False`, `nudged_at=NULL` |

Two things the job must never do, both of which have their own test: touch
`status` (that is the author's field, and Q4 separated them precisely so the
system cannot overwrite it), and treat a spark as activity (TS-6 — otherwise any
passer-by keeps a dead post alive with one click).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from moderation.tasks import NUDGE_AFTER, demote_unanswered, send_nudges, stale_post_nudge
from notifications.models import Notification, NotificationKind
from posts import services as post_services
from posts.models import Post, PostStatus, Role
from social import services as social_services

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )


@pytest.fixture
def stranger(django_user_model):
    return django_user_model.objects.create_user(
        username="dev_krishnan", email="d@example.com", password="pw"
    )


def make_post(author, *, quiet_for=None, **overrides):
    post = post_services.create_post(
        author,
        title="An idea nobody has touched",
        body="x",
        stage="idea",
        commitment="casual",
        roles=[Role.objects.filter(is_curated=True).first()],
    )
    if quiet_for is not None:
        when = timezone.now() - quiet_for
        # `.update()`, not `.save()` — `published_at` has to move too or the
        # `last_activity_at >= published_at` check constraint rejects it.
        Post.objects.filter(pk=post.pk).update(
            last_activity_at=when, published_at=when, **overrides
        )
    elif overrides:
        Post.objects.filter(pk=post.pk).update(**overrides)
    post.refresh_from_db()
    return post


# ── Nudging ─────────────────────────────────────────────────────────────────


def test_a_quiet_post_earns_a_nudge(author):
    post = make_post(author, quiet_for=NUDGE_AFTER + timedelta(days=1))

    assert send_nudges() == 1

    post.refresh_from_db()
    assert post.nudged_at is not None
    # Nudged, not demoted — the author gets asked before anything happens.
    assert post.is_stale is False


def test_the_nudge_reaches_the_author(author):
    """TS-2 — without a notification kind the job can mark a post stale but
    cannot tell anybody, which is a countermeasure nobody sees."""
    post = make_post(author, quiet_for=NUDGE_AFTER + timedelta(days=1))

    send_nudges()

    notification = Notification.objects.get(recipient=author)
    assert notification.kind == NotificationKind.STALE_NUDGE
    assert notification.post == post
    # System-generated: there is no person behind it, and the check constraint
    # enforces that for this kind.
    assert notification.actor is None


def test_a_recent_post_is_left_alone(author):
    make_post(author, quiet_for=timedelta(days=3))

    assert send_nudges() == 0
    assert Notification.objects.count() == 0


def test_nudging_twice_does_nothing_the_second_time(author):
    """`nudged_at` is the guard the candidate query filters on, which is what
    makes the job idempotent — it runs daily."""
    make_post(author, quiet_for=NUDGE_AFTER + timedelta(days=1))

    send_nudges()
    assert send_nudges() == 0
    assert Notification.objects.count() == 1


def test_posts_that_are_not_looking_are_never_nudged(author):
    """"Team formed" is the author saying they are done. Asking them again a
    month later would be the system nagging about a closed question."""
    make_post(
        author,
        quiet_for=NUDGE_AFTER + timedelta(days=1),
        status=PostStatus.TEAM_FORMED,
    )

    assert send_nudges() == 0


# ── Demoting ────────────────────────────────────────────────────────────────


def test_an_unanswered_nudge_demotes_the_post(author):
    post = make_post(author, quiet_for=timedelta(days=60))
    Post.objects.filter(pk=post.pk).update(nudged_at=timezone.now() - timedelta(days=8))

    assert demote_unanswered() == 1

    post.refresh_from_db()
    assert post.is_stale is True
    # The author's own field is untouched — Q4 keeps these separate so the
    # system can never overwrite what they chose.
    assert post.status == PostStatus.LOOKING


def test_a_post_is_not_demoted_before_the_grace_period(author):
    post = make_post(author, quiet_for=timedelta(days=35))
    Post.objects.filter(pk=post.pk).update(nudged_at=timezone.now() - timedelta(days=2))

    assert demote_unanswered() == 0


def test_a_stale_post_is_ranked_lower_not_hidden(client, author):
    """Q4 — `is_stale` demotes, it never hides. Hiding would be the system
    overruling the author, which is the line this feature does not cross."""
    post = make_post(author, quiet_for=timedelta(days=60))
    Post.objects.filter(pk=post.pk).update(is_stale=True)

    from django.urls import reverse

    body = client.get(reverse("posts:feed")).content.decode()

    assert post.title in body


def test_a_fresh_post_sorts_above_a_stale_one(client, author):
    stale = make_post(author, quiet_for=timedelta(days=60))
    Post.objects.filter(pk=stale.pk).update(is_stale=True)
    fresh = post_services.create_post(
        author, title="Posted this morning", body="x", stage="idea", commitment="casual",
        roles=[Role.objects.filter(is_curated=True).first()],
    )

    from django.urls import reverse

    body = client.get(reverse("posts:feed")).content.decode()

    assert body.index(fresh.title) < body.index(stale.title)


# ── Coming back to life ─────────────────────────────────────────────────────


def test_a_comment_revives_a_nudged_post(author, stranger):
    """The third row of the state machine, and it is `touch_activity()`'s work
    rather than the job's — which is why nothing in the job un-stales anything."""
    post = make_post(author, quiet_for=timedelta(days=60))
    send_nudges()
    Post.objects.filter(pk=post.pk).update(is_stale=True)

    social_services.add_comment(stranger, post, "Are you still looking?")

    post.refresh_from_db()
    assert post.is_stale is False
    # Cleared too (TS-10), or the post gets exactly one nudge in its whole life.
    assert post.nudged_at is None


def test_a_spark_does_not_revive_a_post(author, stranger):
    """TS-6 — left in, any passer-by keeps a dead post alive with one click."""
    post = make_post(author, quiet_for=timedelta(days=60))
    send_nudges()
    post.refresh_from_db()
    nudged_at = post.nudged_at

    social_services.toggle_post_spark(stranger, post)

    post.refresh_from_db()
    assert post.nudged_at == nudged_at


def test_answering_the_nudge_revives_the_post(client, author):
    """"Yes, still looking" is one tap from the Alerts screen, and it is one of
    the three documented activity bumps."""
    post = make_post(author, quiet_for=timedelta(days=60))
    send_nudges()
    Post.objects.filter(pk=post.pk).update(is_stale=True)
    client.force_login(author)

    from django.urls import reverse

    client.post(reverse("posts:set_status", args=[post.slug]), {"status": PostStatus.LOOKING})

    post.refresh_from_db()
    assert post.is_stale is False
    assert post.nudged_at is None


# ── The whole job, and its doorway ──────────────────────────────────────────


def test_the_task_nudges_before_it_demotes(author):
    """Order matters: reversed, every post that crossed both thresholds between
    two runs — which is every post the first time this runs against a seeded
    database — is demoted without ever being asked."""
    make_post(author, quiet_for=timedelta(days=90))

    result = stale_post_nudge()

    assert result == {"nudged": 1, "demoted": 0}


def test_the_cron_endpoint_needs_the_shared_secret(client, settings):
    from django.urls import reverse

    settings.CRON_SECRET = "a-real-secret"
    url = reverse("cron:stale_post_nudge")

    # No key, wrong key: 404 rather than 403, which would confirm the endpoint
    # exists and that the key was merely wrong.
    assert client.post(url).status_code == 404
    assert client.post(url, headers={"X-Cron-Key": "wrong"}).status_code == 404

    response = client.post(url, headers={"X-Cron-Key": "a-real-secret"})
    assert response.status_code == 200


def test_the_cron_endpoint_refuses_everything_when_no_secret_is_set(client, settings):
    """A misconfigured deploy should mean a job that does not run, not an open
    endpoint."""
    from django.urls import reverse

    settings.CRON_SECRET = ""

    assert client.post(reverse("cron:stale_post_nudge")).status_code == 404


def test_the_cron_endpoint_is_post_only(client, settings):
    from django.urls import reverse

    settings.CRON_SECRET = "a-real-secret"

    response = client.get(reverse("cron:stale_post_nudge"), headers={"X-Cron-Key": "a-real-secret"})

    assert response.status_code == 405
