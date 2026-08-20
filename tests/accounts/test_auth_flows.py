"""Signup, login and logout — view-level.

Shape follows `testing.md` §2.3: assert the side effect, not just the status
code. A 302 with no user created, or a 200 that quietly logged someone in, both
pass a status-only test.
"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

SIGNUP_DATA = {
    "display_name": "Ananya Iyer",
    "email": "ananya@example.com",
    "username": "ananya_iyer",
    "password1": "correct-horse-battery",
    "password2": "correct-horse-battery",
}


# ── Public access ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("url_name", ["account_login", "account_signup", "account_reset_password"])
def test_auth_pages_are_reachable_logged_out(client, url_name):
    assert client.get(reverse(url_name)).status_code == 200


# ── Signup ──────────────────────────────────────────────────────────────────


def test_signup_creates_a_user_with_a_profile(client, django_user_model):
    response = client.post(reverse("account_signup"), SIGNUP_DATA)

    assert response.status_code == 302
    user = django_user_model.objects.get(username="ananya_iyer")
    assert user.display_name == "Ananya Iyer"
    assert user.email == "ananya@example.com"
    # data-model.md §1.2: created in the same transaction, so every seat can
    # rely on select_related("profile").
    assert user.profile is not None


def test_display_name_is_optional(client, django_user_model):
    """`User.name` falls back to the username, so a blank one is not a problem.

    Asserted rather than assumed: making this field required would be a one-word
    change in the form and would go unnoticed until someone measured signup
    drop-off.
    """
    response = client.post(reverse("account_signup"), {**SIGNUP_DATA, "display_name": ""})

    assert response.status_code == 302
    user = django_user_model.objects.get(username="ananya_iyer")
    assert user.display_name == ""
    assert user.name == "ananya_iyer"


def test_signup_folds_username_case_instead_of_erroring(client, django_user_model):
    """Typing `Ananya_Iyer` should give you `ananya_iyer`, not a red field.

    `User.save()` lowercases anyway, so rejecting the input would be an error
    message about a difference we are about to erase.
    """
    response = client.post(reverse("account_signup"), {**SIGNUP_DATA, "username": "Ananya_Iyer"})

    assert response.status_code == 302
    assert django_user_model.objects.filter(username="ananya_iyer").exists()


@pytest.mark.parametrize("username", ["admin", "feed", "settings", "deleted_1"])
def test_signup_refuses_reserved_usernames(client, django_user_model, username):
    response = client.post(reverse("account_signup"), {**SIGNUP_DATA, "username": username})

    assert response.status_code == 200  # re-rendered with errors, not redirected
    assert not django_user_model.objects.filter(username=username).exists()


def test_signup_refuses_a_duplicate_email_regardless_of_case(client, django_user_model):
    """ACC-13. `Ananya@example.com` and `ananya@example.com` are one account.

    Without the full lowercase in `User.save()` these are two rows under
    `unique=True`, while allauth compares lowercased — so the same address gives
    both a duplicate account and a spurious "already exists" error, depending on
    which code path gets there first.
    """
    django_user_model.objects.create_user(
        username="someone", email="ananya@example.com", password="pw"
    )

    response = client.post(
        reverse("account_signup"), {**SIGNUP_DATA, "email": "Ananya@Example.com"}
    )

    assert response.status_code == 200
    assert django_user_model.objects.filter(email="ananya@example.com").count() == 1


# ── Login and logout ────────────────────────────────────────────────────────


def test_login_with_email(client, django_user_model):
    """ACCOUNT_LOGIN_METHODS = {"email"} — the login field is an email field."""
    django_user_model.objects.create_user(
        username="ananya_iyer", email="ananya@example.com", password="correct-horse-battery"
    )

    response = client.post(
        reverse("account_login"),
        {"login": "ananya@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 302
    assert client.session.get("_auth_user_id")


def test_failed_login_does_not_start_a_session(client, django_user_model):
    django_user_model.objects.create_user(
        username="ananya_iyer", email="ananya@example.com", password="correct-horse-battery"
    )

    response = client.post(
        reverse("account_login"), {"login": "ananya@example.com", "password": "wrong"}
    )

    assert response.status_code == 200
    assert not client.session.get("_auth_user_id")


def test_logout_requires_post(client, django_user_model):
    """A GET must not end the session.

    Link prefetchers and crawlers follow every GET on a page. `testing.md` §6
    applies the same rule to every irreversible action; being logged out at
    random is the cheap version of that bug and the one users notice.
    """
    user = django_user_model.objects.create_user(
        username="ananya_iyer", email="ananya@example.com", password="pw"
    )
    client.force_login(user)

    client.get(reverse("account_logout"))
    assert client.session.get("_auth_user_id"), "GET logged the user out"

    client.post(reverse("account_logout"))
    assert not client.session.get("_auth_user_id")


# ── ADR-0001: the deletion grace window ─────────────────────────────────────


def test_logging_in_cancels_a_pending_deletion(client, django_user_model):
    """ADR-0001: "logging back in during the window cancels it"."""
    from django.utils import timezone

    user = django_user_model.objects.create_user(
        username="ananya_iyer",
        email="ananya@example.com",
        password="correct-horse-battery",
        deletion_requested_at=timezone.now(),
    )

    client.post(
        reverse("account_login"),
        {"login": "ananya@example.com", "password": "correct-horse-battery"},
    )

    user.refresh_from_db()
    assert user.deletion_requested_at is None


def test_login_does_not_resurrect_an_anonymised_account(client, django_user_model):
    """The scrub is final; only the grace window is reversible.

    An anonymised account is `is_active=False` and cannot authenticate at all,
    so this asserts the guard rather than the flow: if a future change ever lets
    one log in, `deletion_requested_at` must not be silently cleared, because it
    is the only record of when the account went.
    """
    from django.utils import timezone

    now = timezone.now()
    user = django_user_model.objects.create_user(
        username="ananya_iyer",
        email="ananya@example.com",
        password="pw",
        deletion_requested_at=now,
        anonymised_at=now,
        is_active=False,
    )

    from accounts.signals import cancel_pending_deletion

    cancel_pending_deletion(sender=django_user_model, request=None, user=user)

    user.refresh_from_db()
    assert user.deletion_requested_at == now


# ── The profile receiver ────────────────────────────────────────────────────


def test_every_user_gets_exactly_one_profile(django_user_model):
    """testing.md §2.2, and QA's factory rule 6 depends on it.

    `UserFactory` must not create a profile — it updates the one the receiver
    made. If this receiver stops firing, that factory starts failing in a way
    that looks like a factory bug.
    """
    from accounts.models import Profile

    user = django_user_model.objects.create_user(
        username="ananya_iyer", email="ananya@example.com", password="pw"
    )

    assert Profile.objects.filter(user=user).count() == 1

    # post_save fires again on update; it must not create a second one or raise.
    user.display_name = "Ananya"
    user.save()
    assert Profile.objects.filter(user=user).count() == 1
