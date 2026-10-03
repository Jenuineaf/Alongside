"""Spark and save — the toggles, their counters, and the double-tap.

Every test here is really about one sentence from the Social seat's review (S3):

> Only adjust a counter when the underlying row was actually created or actually
> deleted.

Two taps on a phone arrive as two requests. The toggles these endpoints replaced
asked `exists()` and then `create()`, which loses that race — both requests see
no row, both insert, one raises `IntegrityError`, and the user gets a 500 on the
signature control of the product. `social/services.py` catches it in a nested
atomic block and treats it as "already on", which is what it is.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from accounts import services as accounts_services
from posts.models import Post, PostSpark, SavedPost
from social import services

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}


@pytest.fixture(autouse=True)
def clear_block_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        username="meera_nair", email="m@example.com", password="pw"
    )


@pytest.fixture
def viewer(django_user_model):
    return django_user_model.objects.create_user(
        username="rohit_k", email="r@example.com", password="pw"
    )


@pytest.fixture
def post(author):
    return Post.objects.create(
        author=author,
        title="I make everything by hand and sell it on WhatsApp",
        slug="handmade-whatsapp-shop",
        body="I need an actual shop, not a catalogue of screenshots.",
        stage="building",
        commitment="casual",
    )


# ── Spark ───────────────────────────────────────────────────────────────────


def test_spark_toggles_the_row_the_counter_and_the_control(client, post, viewer):
    client.force_login(viewer)
    url = reverse("social:spark", kwargs={"pk": post.pk})

    response = client.post(url, headers=HX)
    post.refresh_from_db()
    assert response.status_code == 200
    assert 'aria-pressed="true"' in response.content.decode()
    assert post.spark_count == 1
    assert PostSpark.objects.filter(user=viewer, post=post).count() == 1

    response = client.post(url, headers=HX)
    post.refresh_from_db()
    assert 'aria-pressed="false"' in response.content.decode()
    assert post.spark_count == 0
    assert PostSpark.objects.filter(user=viewer, post=post).exists() is False


def test_spark_never_goes_negative(post, viewer):
    """`spark_count` is a PositiveIntegerField — a CHECK >= 0 in Postgres.

    Decrementing a counter that has already drifted to zero would be an
    `IntegrityError` and a 500 on the button, so the decrement is wrapped in
    `Greatest(..., 0)`.
    """
    PostSpark.objects.create(user=viewer, post=post)  # row with no counter bump

    services.toggle_post_spark(viewer, post)

    post.refresh_from_db()
    assert post.spark_count == 0


def test_spark_does_not_revive_a_post(post, viewer):
    """TS-6 — left in, any passer-by could keep a dead post alive forever."""
    before = post.last_activity_at

    services.toggle_post_spark(viewer, post)

    post.refresh_from_db()
    assert post.last_activity_at == before
    assert post.is_stale is False


def test_anonymous_cannot_spark(client, post):
    response = client.post(reverse("social:spark", kwargs={"pk": post.pk}))

    assert response.status_code == 302
    assert PostSpark.objects.count() == 0


def test_spark_on_a_blocked_authors_post_is_404(client, post, author, viewer):
    accounts_services.block(author, viewer)
    client.force_login(viewer)

    response = client.post(reverse("social:spark", kwargs={"pk": post.pk}), headers=HX)

    assert response.status_code == 404
    assert PostSpark.objects.count() == 0


# ── Save ────────────────────────────────────────────────────────────────────


def test_save_toggles_and_returns_the_control(client, post, viewer):
    """The endpoint used to answer 204 — "make no swap" — leaving the icon hollow."""
    client.force_login(viewer)
    url = reverse("social:save", kwargs={"pk": post.pk})

    response = client.post(url, headers=HX)
    assert response.status_code == 200
    assert 'aria-pressed="true"' in response.content.decode()
    assert SavedPost.objects.filter(user=viewer, post=post).count() == 1

    response = client.post(url, headers=HX)
    assert 'aria-pressed="false"' in response.content.decode()
    assert SavedPost.objects.filter(user=viewer, post=post).exists() is False


def test_save_moves_save_count(client, post, viewer):
    """§7 lists `save_count`; the first version of this endpoint never wrote it.

    Nothing renders the number yet, which is exactly why the drift would have
    been found months later with no screen to check it against.
    """
    client.force_login(viewer)
    url = reverse("social:save", kwargs={"pk": post.pk})

    client.post(url, headers=HX)
    post.refresh_from_db()
    assert post.save_count == 1

    client.post(url, headers=HX)
    post.refresh_from_db()
    assert post.save_count == 0


def test_save_is_private(client, post, viewer, author):
    """A save is never visible to anyone else — unlike a spark.

    Checked on the feed rather than post detail, because the feed card is the
    only surface that renders the save control at all.
    """
    client.force_login(viewer)
    client.post(reverse("social:save", kwargs={"pk": post.pk}), headers=HX)

    client.force_login(author)
    body = client.get(reverse("posts:feed")).content.decode()

    assert post.title in body
    assert 'aria-pressed="true"' not in body


def test_save_on_a_blocked_authors_post_is_404(client, post, author, viewer):
    accounts_services.block(viewer, author)
    client.force_login(viewer)

    response = client.post(reverse("social:save", kwargs={"pk": post.pk}), headers=HX)

    assert response.status_code == 404
    assert SavedPost.objects.count() == 0
