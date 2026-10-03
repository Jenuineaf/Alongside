"""Notifications — the two triggers, both dedup rules, and the deletes.

Notifications are the retention engine (spec §8), so a noisy bell is a product
failure rather than a cosmetic one. Every test here is about the bell saying the
right number:

- the two triggers that exist fire, and the one that must not (**spark**) never does
- repeat follows collapse into one unread row (S5)
- repeat comments inside 60 seconds collapse; outside it, they don't (rule 1 / S6)
- a notification never outlives the thing it points at (S8)
- blocking empties the bell in both directions (ADR-0002)
- nobody is ever notified about their own action
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from accounts import services as accounts_services
from notifications import services as notification_services
from notifications.models import Notification, NotificationKind
from posts.models import Post
from social import services as social_services

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_block_cache():
    cache.clear()
    yield
    cache.clear()


def make_user(django_user_model, username):
    return django_user_model.objects.create_user(
        username=username, email=f"{username}@example.com", password="pw"
    )


@pytest.fixture
def author(django_user_model):
    return make_user(django_user_model, "ananya_iyer")


@pytest.fixture
def joiner(django_user_model):
    return make_user(django_user_model, "dev_krishnan")


@pytest.fixture
def post(author):
    return Post.objects.create(
        author=author,
        title="A 40-minute window for surplus food",
        slug="surplus-food-window",
        body="Restaurants have food left at closing and nobody to take it.",
        stage="idea",
        commitment="serious",
    )


# ── New comment ─────────────────────────────────────────────────────────────


def test_a_comment_notifies_the_post_author(post, author, joiner):
    social_services.add_comment(joiner, post, "Android dev here, free weekends.")

    notification = Notification.objects.get(recipient=author)
    assert notification.kind == NotificationKind.NEW_COMMENT
    assert notification.actor == joiner
    # `post` AND `comment`: the Alerts row needs the post's title, and
    # `notification_kind_targets` requires both.
    assert notification.post == post
    assert notification.comment is not None
    assert notification.is_read is False


def test_commenting_on_your_own_idea_notifies_nobody(post, author):
    social_services.add_comment(author, post, "Adding a thought of my own.")

    assert Notification.objects.count() == 0


def test_two_comments_inside_the_window_make_one_notification(post, joiner):
    """Rule 1 — a double-submit guard."""
    social_services.add_comment(joiner, post, "first")
    social_services.add_comment(joiner, post, "second, 200ms later")

    assert Notification.objects.filter(kind=NotificationKind.NEW_COMMENT).count() == 1


def test_two_comments_outside_the_window_make_two(post, joiner):
    """Rule 1 is deliberately NOT a burst guard (S6, awaiting Jeni's ruling).

    Five comments over an hour is five things to read. If that ruling ever goes
    the other way, this is the test that changes.
    """
    social_services.add_comment(joiner, post, "first")
    Notification.objects.update(created_at=timezone.now() - timedelta(seconds=61))

    social_services.add_comment(joiner, post, "second, much later")

    assert Notification.objects.filter(kind=NotificationKind.NEW_COMMENT).count() == 2


def test_two_different_people_both_notify(post, joiner, django_user_model):
    other = make_user(django_user_model, "sneha_v")

    social_services.add_comment(joiner, post, "from one person")
    social_services.add_comment(other, post, "from another")

    assert Notification.objects.filter(kind=NotificationKind.NEW_COMMENT).count() == 2


# ── New follower ────────────────────────────────────────────────────────────


def test_a_follow_notifies(author, joiner):
    accounts_services.follow(joiner, author)

    notification = Notification.objects.get(recipient=author)
    assert notification.kind == NotificationKind.NEW_FOLLOWER
    assert notification.actor == joiner
    # `notification_kind_targets` requires both to be null for this kind.
    assert notification.post is None
    assert notification.comment is None


def test_repeat_follows_collapse_into_one_unread_row(author, joiner):
    """S5, ruled yes by Jeni. Follow is freely toggleable, so without this one
    person could bury everything else in somebody's bell."""
    accounts_services.follow(joiner, author)
    first = Notification.objects.get(recipient=author)
    Notification.objects.update(created_at=timezone.now() - timedelta(hours=2))

    accounts_services.unfollow(joiner, author)
    accounts_services.follow(joiner, author)

    assert Notification.objects.filter(recipient=author).count() == 1
    bumped = Notification.objects.get(recipient=author)
    assert bumped.pk == first.pk
    # Bumped, not re-created — and bumped via `.update()`, because `created_at`
    # is `auto_now_add` and a `.save()` would silently not move it (S4 footgun).
    assert bumped.created_at > timezone.now() - timedelta(minutes=1)


def test_a_follow_after_reading_makes_a_fresh_notification(author, joiner):
    """"Mark all read" is the dedup reset — both rules key on is_read=False."""
    accounts_services.follow(joiner, author)
    notification_services.mark_all_read(author)
    accounts_services.unfollow(joiner, author)

    accounts_services.follow(joiner, author)

    assert Notification.objects.filter(recipient=author).count() == 2
    assert Notification.objects.filter(recipient=author, is_read=False).count() == 1


def test_re_pressing_follow_does_not_re_notify(author, joiner):
    """`get_or_create` collapsed the edge, so nothing happened to notify about."""
    accounts_services.follow(joiner, author)
    notification_services.mark_all_read(author)

    accounts_services.follow(joiner, author)  # no unfollow in between

    assert Notification.objects.filter(recipient=author).count() == 1


def test_nobody_is_notified_about_their_own_action(author):
    """The fan-out's own guard, not the edge's.

    `Follow` already has a `follow_not_self` check constraint and the view 404s,
    so a self-follow cannot reach the service through the app. The guard is here
    anyway because `notification_not_self` is a check constraint too — reaching
    it would be an `IntegrityError` on a follow that had already succeeded, and
    fan-out must never take the action down with it.
    """
    assert notification_services.notify_new_follower(author, author) is None
    assert Notification.objects.count() == 0


# ── The one that must never fire ────────────────────────────────────────────


def test_sparks_never_notify(post, joiner, author):
    """§2.7 — spec §4.6 lists exactly three triggers and sparks is not among
    them. Deliberate: spark notifications are noise."""
    comment = social_services.add_comment(author, post, "my own idea")
    Notification.objects.all().delete()

    social_services.toggle_post_spark(joiner, post)
    social_services.toggle_comment_spark(joiner, comment)
    social_services.toggle_save(joiner, post)

    assert Notification.objects.count() == 0


# ── Nothing outlives its target (S8) ────────────────────────────────────────


def test_deleting_a_comment_deletes_its_notification(post, joiner):
    comment = social_services.add_comment(joiner, post, "Mistyped this one.")
    assert Notification.objects.count() == 1

    social_services.soft_delete_comment(comment)

    assert Notification.objects.count() == 0


def test_dropping_a_posts_notifications_covers_its_comments(post, joiner, django_user_model):
    """Every `new_comment` row carries `post` as well as `comment`, which is what
    makes the post-level sweep sufficient on its own."""
    other = make_user(django_user_model, "priya_shetty")
    social_services.add_comment(joiner, post, "one")
    social_services.add_comment(other, post, "two")
    assert Notification.objects.count() == 2

    notification_services.drop_for_post(post)

    assert Notification.objects.count() == 0


# ── Blocking (ADR-0002) ─────────────────────────────────────────────────────


def test_blocking_empties_the_bell_in_both_directions(post, author, joiner):
    social_services.add_comment(joiner, post, "I would like to help.")
    accounts_services.follow(author, joiner)
    assert Notification.objects.count() == 2

    accounts_services.block(author, joiner)

    assert Notification.objects.count() == 0


def test_the_bell_count_also_filters_blocked_actors(post, author, joiner):
    """The delete is the permanent half; the filter is the half that holds if a
    delete is ever missed or lost to a failed transaction (S9)."""
    social_services.add_comment(joiner, post, "I would like to help.")
    # A block row with no cleanup — what a missed delete looks like.
    from accounts.models import Block

    Block.objects.create(blocker=author, blocked=joiner)

    assert Notification.objects.filter(recipient=author).count() == 1
    assert notification_services.unread_count(author) == 0


# ── The screen ──────────────────────────────────────────────────────────────


def test_alerts_screen_groups_new_and_earlier(client, post, author, joiner):
    social_services.add_comment(joiner, post, "This one is unread.")
    notification_services.mark_all_read(author)
    accounts_services.follow(joiner, author)
    client.force_login(author)

    body = client.get(reverse("notifications:list")).content.decode()

    assert "New" in body
    assert "Earlier" in body
    assert "followed you" in body
    assert "This one is unread." in body


def test_alerts_screen_shows_a_follow_note(client, author, joiner):
    """The note is the one that is actually worth opening — the Designer."""
    accounts_services.follow(joiner, author, note="Saw your Kotlin comment.")
    client.force_login(author)

    body = client.get(reverse("notifications:list")).content.decode()

    assert "Saw your Kotlin comment." in body


def test_alerts_screen_requires_signing_in(client):
    response = client.get(reverse("notifications:list"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_mark_all_read_clears_the_badge(client, post, author, joiner):
    social_services.add_comment(joiner, post, "unread")
    client.force_login(author)
    assert notification_services.unread_count(author) == 1

    response = client.post(reverse("notifications:mark_all_read"))

    assert response.status_code == 302
    assert notification_services.unread_count(author) == 0


def test_mark_all_read_is_post_only(client, author):
    client.force_login(author)

    assert client.get(reverse("notifications:mark_all_read")).status_code == 405


def test_the_badge_is_free_for_anonymous_visitors(client, post, joiner):
    """CLAUDE.md rule 7 — the public feed must not acquire a count query just
    because a context processor exists."""
    from notifications.context_processors import unread_alerts

    class Request:
        user = None

    assert unread_alerts(Request()) == {}
    assert client.get(reverse("posts:feed")).status_code == 200
