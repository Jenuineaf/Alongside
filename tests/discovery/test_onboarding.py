"""Onboarding — three steps, and the promise that none of them is mandatory.

The sign-up screen tells people this is optional and editable later. A flow that
quietly requires an answer breaks that promise at the worst possible moment —
before they have seen anything the product does. So the load-bearing test here
is not "the form saves", it is **"skipping every step still finishes"**.

`onboarding_completed_at` means "reached the end by any path, including skipping
everything" (§1.2) — not "answered the questions". That distinction is what lets
us re-prompt somebody who bounced halfway without nagging somebody who chose to
skip, and both cases are covered below.
"""

import pytest
from django.urls import reverse

from accounts.models import Follow, ProfileInterest
from posts.models import Tag

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="jeni_dev", email="j@example.com", password="pw"
    )


@pytest.fixture
def curated_tags(db):
    return list(Tag.objects.filter(is_curated=True).order_by("pk")[:3])


def step_url(step):
    return reverse("discovery:onboarding_step", kwargs={"step": step})


# ── The happy path ──────────────────────────────────────────────────────────


def test_step_1_saves_purpose_and_moves_on(client, user):
    client.force_login(user)

    response = client.post(step_url(1), {"purpose": "find"})

    assert response.status_code == 302
    assert response["Location"] == step_url(2)
    user.profile.refresh_from_db()
    assert user.profile.purpose == "find"


def test_step_2_saves_the_field_that_unlocks_home_tier_2(client, user, curated_tags):
    field = curated_tags[0]
    client.force_login(user)

    client.post(step_url(2), {"field_tag": str(field.pk), "occupation": "Android dev"})

    user.profile.refresh_from_db()
    assert user.profile.field_tag_id == field.pk
    assert user.profile.occupation == "Android dev"
    # The profile's search vector carries occupation, so skipping the rebuild
    # here makes people search stale from the moment onboarding runs.
    assert user.profile.search_vector is not None


def test_step_3_writes_interests_and_finishes(client, user, curated_tags):
    client.force_login(user)

    response = client.post(step_url(3), {"interests": [str(t.pk) for t in curated_tags[:2]]})

    assert response.status_code == 302
    assert response["Location"] == reverse("posts:home")
    assert ProfileInterest.objects.filter(profile=user.profile).count() == 2
    user.profile.refresh_from_db()
    assert user.profile.onboarding_completed_at is not None


def test_step_3_replaces_interests_rather_than_appending(client, user, curated_tags):
    ProfileInterest.objects.create(profile=user.profile, tag=curated_tags[0])
    client.force_login(user)

    client.post(step_url(3), {"interests": [str(curated_tags[1].pk)]})

    assert list(user.profile.interests.values_list("pk", flat=True)) == [curated_tags[1].pk]


# ── Skipping — the path that must work ──────────────────────────────────────


def test_skipping_every_step_still_finishes(client, user):
    """The whole promise, in one test."""
    client.force_login(user)

    for step in (1, 2, 3):
        response = client.post(step_url(step), {"skip": "1"})
        assert response.status_code == 302

    user.profile.refresh_from_db()
    assert user.profile.onboarding_completed_at is not None
    assert user.profile.purpose == ""
    assert user.profile.field_tag_id is None
    assert user.profile.interests.count() == 0


def test_skipping_writes_nothing_even_when_the_form_was_filled_in(client, user, curated_tags):
    """Skip is a real control, not a styled Next."""
    client.force_login(user)

    client.post(step_url(2), {"skip": "1", "field_tag": str(curated_tags[0].pk)})

    user.profile.refresh_from_db()
    assert user.profile.field_tag_id is None


def test_an_unfinished_flow_leaves_the_marker_unset(client, user):
    """Bounced halfway — re-promptable, which is the point of the distinction."""
    client.force_login(user)

    client.post(step_url(1), {"purpose": "post"})

    user.profile.refresh_from_db()
    assert user.profile.onboarding_completed_at is None


# ── Validation and bounds ───────────────────────────────────────────────────


def test_too_many_interests_is_rejected_without_losing_the_step(client, user):
    many = list(Tag.objects.filter(is_curated=True).order_by("pk")[:9])
    if len(many) < 9:  # pragma: no cover - depends on the seeded vocabulary
        pytest.skip("needs at least 9 curated tags")
    client.force_login(user)

    response = client.post(step_url(3), {"interests": [str(t.pk) for t in many]})

    assert response.status_code == 200
    assert ProfileInterest.objects.count() == 0


def test_a_step_out_of_range_is_clamped(client, user):
    client.force_login(user)

    assert client.get(reverse("discovery:onboarding_step", kwargs={"step": 9})).status_code == 200


def test_onboarding_requires_signing_in(client):
    response = client.get(reverse("discovery:onboarding"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


# ── Suggested follows ───────────────────────────────────────────────────────


def test_suggested_follows_appear_on_the_last_step(client, user, django_user_model):
    django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )
    client.force_login(user)

    body = client.get(step_url(3)).content.decode()

    assert "People worth following" in body
    assert "ananya_iyer" in body or "Follow" in body


def test_following_from_onboarding_comes_back_to_onboarding(client, user, django_user_model):
    """Otherwise the flow is abandoned at step 3 — the step that writes
    `onboarding_completed_at`."""
    other = django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )
    client.force_login(user)

    response = client.post(
        reverse("accounts:follow", args=[other.username]), {"next": step_url(3)}
    )

    assert response["Location"] == step_url(3)
    assert Follow.objects.filter(follower=user, following=other).exists()


def test_follow_next_cannot_bounce_you_off_site(client, user, django_user_model):
    """A bare `redirect(request.POST["next"])` is an open redirect."""
    other = django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )
    client.force_login(user)

    response = client.post(
        reverse("accounts:follow", args=[other.username]), {"next": "https://example.com/phish"}
    )

    assert response["Location"] == other.get_absolute_url()


def test_the_demo_account_is_never_suggested(client, user, django_user_model):
    """It is shared by every visitor; following it is meaningless."""
    django_user_model.objects.create_user(
        username="demo_account", email="demo@example.com", password="pw", is_public_demo=True
    )
    client.force_login(user)

    body = client.get(step_url(3)).content.decode()

    assert "demo_account" not in body
