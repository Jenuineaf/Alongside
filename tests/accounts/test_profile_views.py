"""Profile, settings and deletion views.

Shape follows `testing.md` §2.3: **assert the side effect, not just the status
code.** A 302 that still wrote the row is the bug these are for.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile

pytestmark = pytest.mark.django_db


def make_user(django_user_model, username="ananya_iyer", **kwargs):
    return django_user_model.objects.create_user(
        username=username,
        email=kwargs.pop("email", f"{username}@example.com"),
        password=kwargs.pop("password", "correct-horse-battery"),
        **kwargs,
    )


# ── Public read access (CONTRIBUTING.md rule 7) ───────────────────────────────────


def test_profile_is_public(client, django_user_model):
    """Non-negotiable. This is the test that stops a login wall creeping back."""
    user = make_user(django_user_model)
    response = client.get(reverse("accounts:profile", args=[user.username]))
    assert response.status_code == 200
    assert user.username in response.content.decode()


def test_profile_of_unknown_user_404s(client):
    assert client.get(reverse("accounts:profile", args=["nobody_here"])).status_code == 404


def test_profile_url_is_case_insensitive(client, django_user_model):
    """Usernames are lowercased on save, so `/u/Ananya_Iyer/` must still resolve.

    Otherwise a link someone typed by hand, or an old capitalised link, 404s on
    an account that plainly exists.
    """
    make_user(django_user_model)
    assert client.get("/u/Ananya_Iyer/").status_code == 200


def test_anonymised_profile_404s(client, django_user_model):
    """ADR-0001: nothing survives the scrub worth rendering a page for."""
    user = make_user(django_user_model, anonymised_at=timezone.now(), is_active=False)
    assert client.get(reverse("accounts:profile", args=[user.username])).status_code == 404


@pytest.mark.parametrize(
    "url_name", ["accounts:settings", "accounts:profile_edit", "accounts:blocked"]
)
def test_private_screens_redirect_anonymous_to_login(client, url_name):
    response = client.get(reverse(url_name))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_settings_url_is_not_swallowed_by_the_username_pattern(client, django_user_model):
    """`/u/settings/` must be Settings, not a profile lookup for "settings".

    `<str:username>/` would match it if the literal paths were not declared
    first — and because "settings" is a reserved username the failure would be a
    404 on the settings page, which reads as a routing bug with no obvious cause.
    """
    user = make_user(django_user_model)
    client.force_login(user)
    response = client.get(reverse("accounts:settings"))
    assert response.status_code == 200
    assert response.resolver_match.url_name == "settings"


# ── Editing ─────────────────────────────────────────────────────────────────


def test_profile_edit_saves_and_cannot_target_anyone_else(client, django_user_model):
    """The view takes its target from the session, so there is nothing to spoof."""
    user = make_user(django_user_model)
    other = make_user(django_user_model, "sneha_v")
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "Ananya Iyer",
            "headline": "Final-year CS",
            "occupation": "Student",
            "bio": "I like problems where the software is the easy part.",
            "work_done": "",
            "city": "Bengaluru",
            "is_remote_friendly": "on",
            "github_url": "",
            "portfolio_url": "",
            "website_url": "",
            "custom_skills": "cold chains, logistics",
        },
    )

    assert response.status_code == 302
    user.refresh_from_db()
    profile = Profile.objects.get(user=user)
    assert user.display_name == "Ananya Iyer"
    assert profile.headline == "Final-year CS"
    assert profile.custom_skills == ["cold chains", "logistics"]
    # Derived, never typed (data-model.md §9 Q6).
    assert profile.city_slug == "bengaluru"

    other.refresh_from_db()
    assert other.display_name == ""


def test_custom_skills_are_capped_at_three(client, django_user_model):
    user = make_user(django_user_model)
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "",
            "headline": "",
            "occupation": "",
            "bio": "",
            "work_done": "",
            "city": "",
            "github_url": "",
            "portfolio_url": "",
            "website_url": "",
            "custom_skills": "one, two, three, four",
        },
    )

    assert response.status_code == 200  # re-rendered with errors
    assert Profile.objects.get(user=user).custom_skills == []


def test_bio_length_is_enforced_in_the_form(client, django_user_model):
    """`TextField(500)` is a form limit only — Postgres does not enforce it
    (data-model.md §0). If `clean_bio` goes, the limit goes silently with it."""
    user = make_user(django_user_model)
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile_edit"),
        {
            "display_name": "",
            "headline": "",
            "occupation": "",
            "bio": "x" * 501,
            "work_done": "",
            "city": "",
            "github_url": "",
            "portfolio_url": "",
            "website_url": "",
            "custom_skills": "",
        },
    )

    assert response.status_code == 200
    assert Profile.objects.get(user=user).bio == ""


# ── Account deletion (ADR-0001) ─────────────────────────────────────────────


def test_delete_account_get_does_not_delete_anything(client, django_user_model):
    """A GET must never start the clock.

    Every link prefetcher and crawler follows GETs. `testing.md` §6 makes this a
    rule for all irreversible actions; this is the most irreversible one there is.
    """
    user = make_user(django_user_model)
    client.force_login(user)

    response = client.get(reverse("accounts:delete_account"))

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.deletion_requested_at is None


def test_delete_account_post_starts_the_grace_window(client, django_user_model):
    user = make_user(django_user_model)
    client.force_login(user)

    client.post(reverse("accounts:delete_account"))

    user.refresh_from_db()
    assert user.deletion_requested_at is not None
    # Nothing is scrubbed yet — that is the day-30 job's work.
    assert user.anonymised_at is None
    assert user.is_active is True
    assert user.email == "ananya_iyer@example.com"


def test_requesting_deletion_twice_does_not_restart_the_clock(client, django_user_model):
    """Otherwise re-requesting keeps an account alive past its own deadline."""
    user = make_user(django_user_model)
    client.force_login(user)

    client.post(reverse("accounts:delete_account"))
    user.refresh_from_db()
    first = user.deletion_requested_at

    client.post(reverse("accounts:delete_account"))
    user.refresh_from_db()
    assert user.deletion_requested_at == first


def test_cancel_deletion_clears_the_window(client, django_user_model):
    user = make_user(django_user_model, deletion_requested_at=timezone.now())
    client.force_login(user)

    client.post(reverse("accounts:cancel_deletion"))

    user.refresh_from_db()
    assert user.deletion_requested_at is None


def test_cancel_deletion_requires_post(client, django_user_model):
    """A GET must not cancel anything.

    Note the ordering: logging in **is itself** a cancel (ADR-0001), so the
    window has to be opened *after* `force_login` or there is nothing left for
    the GET to fail to change.
    """
    user = make_user(django_user_model)
    client.force_login(user)
    django_user_model.objects.filter(pk=user.pk).update(deletion_requested_at=timezone.now())

    assert client.get(reverse("accounts:cancel_deletion")).status_code == 405
    user.refresh_from_db()
    assert user.deletion_requested_at is not None
