"""Comments — the rows, the counter, the permissions, and the block filter.

Four contracts are under test here, and they fail in four different ways:

1. **`Post.comment_count` tracks the rows that exist** (§7, §7.1). When it
   doesn't, the post reads "12 comments" above 11 rendered ones, which looks
   like a caching bug and isn't.
2. **A comment bumps `last_activity_at` and clears `is_stale`** (`touch_activity`).
   When it doesn't, a post that just collected five comments stays demoted to
   the bottom of every feed and nothing errors.
3. **Only the author can delete, and somebody else is a 404** (`testing.md` §5.2).
4. **Blocked people are invisible in both directions** (ADR-0002), including at
   the endpoint — the card is never rendered, but the URL is guessable.
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from accounts import services as accounts_services
from posts.models import Comment, Post, PostStatus
from social import services

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}


@pytest.fixture(autouse=True)
def clear_block_cache():
    """ADR-0003 caches the block set per user; a leaked set fails the next test."""
    cache.clear()
    yield
    cache.clear()


def make_user(django_user_model, username, **extra):
    return django_user_model.objects.create_user(
        username=username, email=f"{username}@example.com", password="pw", **extra
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


def comment_url(post):
    return reverse("social:comment_create", kwargs={"pk": post.pk})


# ── Creating ────────────────────────────────────────────────────────────────


def test_comment_is_written_and_counted(client, post, joiner):
    client.force_login(joiner)

    response = client.post(
        comment_url(post), {"body": "Android dev here, free weekends."}, headers=HX
    )

    assert response.status_code == 200
    comment = Comment.objects.get(post=post)
    assert comment.author == joiner
    assert comment.body == "Android dev here, free weekends."
    post.refresh_from_db()
    assert post.comment_count == 1


def test_comment_revives_a_stale_post(client, joiner, author):
    """A comment is the strongest signal a post is alive — TS-10, PF-2.

    Asserts the flag and the nudge timestamp, not just `last_activity_at`.
    Nothing else in the original design ever set `is_stale` back to `False`, and
    without clearing `nudged_at` a post gets exactly one nudge in its life.
    """
    old = timezone.now() - timedelta(days=45)
    stale = Post.objects.create(
        author=author,
        title="A Kannada-first OCR for old land records",
        slug="kannada-ocr",
        body="The records are scanned but not searchable.",
        stage="building",
        commitment="serious",
        published_at=old,
        last_activity_at=old,
        is_stale=True,
        nudged_at=old,
    )
    client.force_login(joiner)

    client.post(
        comment_url(stale), {"body": "The hostel wardens keep a paper log already."}, headers=HX
    )

    stale.refresh_from_db()
    assert stale.is_stale is False
    assert stale.nudged_at is None
    assert stale.last_activity_at > old


def test_blank_comment_is_rejected_without_touching_the_counter(client, post, joiner):
    """Status 200, because HTMX only swaps 2xx and the error has to reach the user."""
    client.force_login(joiner)

    response = client.post(comment_url(post), {"body": "   "}, headers=HX)

    assert response.status_code == 200
    assert "Write something first." in response.content.decode()
    assert Comment.objects.filter(post=post).count() == 0
    post.refresh_from_db()
    assert post.comment_count == 0


def test_comment_without_htmx_redirects_to_the_thread(client, post, joiner):
    """The form is a plain HTML form that happens to be enhanced."""
    client.force_login(joiner)

    response = client.post(comment_url(post), {"body": "Worth copying before you build routing."})

    assert response.status_code == 302
    assert response["Location"] == f"{post.get_absolute_url()}#comments"
    assert Comment.objects.filter(post=post).count() == 1


def test_anonymous_cannot_comment(client, post):
    response = client.post(comment_url(post), {"body": "hello"})

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert Comment.objects.count() == 0


def test_public_demo_account_is_refused(client, post, django_user_model):
    """§1.1.1 — the shared login may spark and save, but may not add content.

    A real permission check, not a hidden button: the endpoint is what QA
    asserts as the sixth actor in the permission matrix.
    """
    demo = make_user(django_user_model, "demo_account", is_public_demo=True)
    client.force_login(demo)

    response = client.post(comment_url(post), {"body": "graffiti"}, headers=HX)

    assert response.status_code == 403
    assert Comment.objects.count() == 0


def test_get_is_not_allowed(client, post, joiner):
    client.force_login(joiner)

    assert client.get(comment_url(post)).status_code == 405


def test_comment_on_a_deleted_post_is_404(client, post, joiner):
    post.deleted_at = timezone.now()
    post.save(update_fields=["deleted_at"])
    client.force_login(joiner)

    assert client.post(comment_url(post), {"body": "hello"}, headers=HX).status_code == 404


# ── Deleting ────────────────────────────────────────────────────────────────


def test_author_deletes_own_comment_and_the_count_follows(client, post, joiner):
    comment = services.add_comment(joiner, post, "Mistyped this one.")
    client.force_login(joiner)

    response = client.post(
        reverse("social:comment_delete", kwargs={"pk": comment.pk}), headers=HX
    )

    assert response.status_code == 200
    # Soft, not hard: the row survives for a report that may point at it (§8).
    assert Comment.all_objects.filter(pk=comment.pk).exists()
    assert Comment.objects.filter(pk=comment.pk).exists() is False
    post.refresh_from_db()
    assert post.comment_count == 0


def test_deleting_somebody_elses_comment_is_404(client, post, author, joiner):
    comment = services.add_comment(joiner, post, "Not yours to remove.")
    client.force_login(author)

    response = client.post(
        reverse("social:comment_delete", kwargs={"pk": comment.pk}), headers=HX
    )

    assert response.status_code == 404
    assert Comment.objects.filter(pk=comment.pk).exists()
    post.refresh_from_db()
    assert post.comment_count == 1


def test_deleting_twice_moves_the_counter_once(client, post, joiner):
    """S3 — a delete that removed zero rows is a no-op for the counter.

    Two taps on a flaky connection arrive as two requests. Two things stop the
    second one double-decrementing, and both are deliberate: the view looks the
    comment up through the active manager, so an already-deleted one is a 404,
    and the service's `UPDATE … WHERE deleted_at IS NULL` means only the request
    that actually wrote the row may touch the counter. The second is what holds
    if the view is ever bypassed.
    """
    services.add_comment(joiner, post, "one")
    comment = services.add_comment(joiner, post, "two")
    client.force_login(joiner)
    url = reverse("social:comment_delete", kwargs={"pk": comment.pk})

    assert client.post(url, headers=HX).status_code == 200
    assert client.post(url, headers=HX).status_code == 404
    # Belt and braces: the service alone, on a stale instance, is also a no-op.
    assert services.soft_delete_comment(comment) is False

    post.refresh_from_db()
    assert post.comment_count == 1


# ── Sparks on comments ──────────────────────────────────────────────────────


def test_comment_spark_toggles(client, post, author, joiner):
    comment = services.add_comment(author, post, "Worth copying before you build routing.")
    client.force_login(joiner)
    url = reverse("social:comment_spark", kwargs={"pk": comment.pk})

    client.post(url, headers=HX)
    comment.refresh_from_db()
    assert comment.spark_count == 1

    response = client.post(url, headers=HX)
    comment.refresh_from_db()
    assert comment.spark_count == 0
    assert 'aria-pressed="false"' in response.content.decode()


def test_comment_spark_does_not_revive_the_post(client, post, author, joiner):
    """TS-6 — a spark is a stranger's one click and says nothing about the author."""
    comment = services.add_comment(author, post, "Nice.")
    post.refresh_from_db()
    before = post.last_activity_at
    client.force_login(joiner)

    client.post(reverse("social:comment_spark", kwargs={"pk": comment.pk}), headers=HX)

    post.refresh_from_db()
    assert post.last_activity_at == before


# ── Blocking (ADR-0002) ─────────────────────────────────────────────────────


def test_blocked_viewer_cannot_comment_by_url(client, post, author, joiner):
    """The card is never rendered, but `/s/post/41/comment/` is guessable."""
    accounts_services.block(author, joiner)
    client.force_login(joiner)

    assert client.post(comment_url(post), {"body": "hello"}, headers=HX).status_code == 404


def test_block_hides_the_comment_but_not_the_counter(
    client, post, author, joiner, django_user_model
):
    """§7.2 — counters are global; the thread is filtered.

    A viewer-relative count would leak exactly how many comments the blocked
    person wrote. The heading on post detail renders the length of the filtered
    list instead, which is why both numbers may legitimately differ.
    """
    noisy = make_user(django_user_model, "sneha_v")
    services.add_comment(noisy, post, "You cannot see this.")
    services.add_comment(author, post, "You can see this.")
    accounts_services.block(joiner, noisy)
    client.force_login(joiner)

    response = client.get(post.get_absolute_url())
    body = response.content.decode()

    assert response.status_code == 200
    assert "You cannot see this." not in body
    assert "You can see this." in body
    post.refresh_from_db()
    assert post.comment_count == 2


def test_comment_spark_on_a_blocked_authors_post_is_404(
    client, post, author, joiner, django_user_model
):
    """Two block rules meet here: the comment's author, and the post's.

    The comment belongs to somebody the viewer can see; the post it hangs under
    does not. A lookup that only filtered `Comment.author` would let this
    through.
    """
    commenter = make_user(django_user_model, "priya_shetty")
    comment = services.add_comment(commenter, post, "Visible author, hidden post.")
    accounts_services.block(joiner, author)
    client.force_login(joiner)

    response = client.post(reverse("social:comment_spark", kwargs={"pk": comment.pk}), headers=HX)

    assert response.status_code == 404


# ── The thread on the page ──────────────────────────────────────────────────


def test_post_detail_shows_the_thread_and_a_matching_tally(client, post, author, joiner):
    services.add_comment(joiner, post, "Android dev here, free weekends.")
    client.force_login(author)

    body = client.get(post.get_absolute_url()).content.decode()

    assert "Android dev here, free weekends." in body
    assert 'id="post-comment-tally"' in body
    assert 'id="comment-section"' in body


def test_anonymous_sees_the_thread_and_no_form(client, post, joiner):
    """CONTRIBUTING.md rule 7 — reading never needs an account."""
    services.add_comment(joiner, post, "Readable without signing in.")

    body = client.get(post.get_absolute_url()).content.decode()

    assert "Readable without signing in." in body
    assert "Join the conversation" in body
    assert reverse("social:comment_create", kwargs={"pk": post.pk}) not in body


def test_team_formed_posts_still_accept_comments(client, post, joiner):
    """Status takes a post out of the feed; it does not close the conversation."""
    post.status = PostStatus.TEAM_FORMED
    post.save(update_fields=["status"])
    client.force_login(joiner)

    response = client.post(
        comment_url(post), {"body": "Congrats — how did you find them?"}, headers=HX
    )

    assert response.status_code == 200
    assert Comment.objects.filter(post=post).count() == 1
