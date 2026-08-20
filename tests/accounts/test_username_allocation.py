"""Username allocation — the half that needs the database.

Deliberately uses pytest-django's `django_user_model` and the bare `client`
rather than fixtures: `tests/conftest.py` and the factories are QA's and do not
exist yet (`testing.md` §11), and a feature seat inventing its own `UserFactory`
is exactly the duplication §3 exists to prevent.
"""

import pytest

from accounts.usernames import FALLBACK_STEM, MAX_LENGTH, generate_unique_username, is_available

pytestmark = pytest.mark.django_db


def test_free_name_is_used_as_is(django_user_model):
    assert generate_unique_username("Ananya Iyer") == "ananya_iyer"


def test_first_usable_candidate_wins():
    """Candidates are tried in order, and too-short ones are skipped.

    This is the Google case: the display name is the nicer handle, so it is
    offered first, and the email is the fallback when the name yields nothing.
    """
    assert generate_unique_username("", "Jeni Verse", "other@x.com") == "jeni_verse"
    assert generate_unique_username("🚀", "ab", "ananya@x.com") == "ananya"


def test_falls_back_when_nothing_survives():
    assert generate_unique_username("🚀🚀", "अनन्या", None) == FALLBACK_STEM


def test_collision_gets_a_numeric_suffix(django_user_model):
    django_user_model.objects.create_user(username="ananya_iyer", email="a@x.com", password="pw")
    assert generate_unique_username("Ananya Iyer") == "ananya_iyer_2"


def test_repeated_collisions_keep_counting(django_user_model):
    for name in ("ananya_iyer", "ananya_iyer_2", "ananya_iyer_3"):
        django_user_model.objects.create_user(username=name, email=f"{name}@x.com", password="pw")
    assert generate_unique_username("Ananya Iyer") == "ananya_iyer_4"


def test_suffixed_username_still_fits_the_column(django_user_model):
    """A 30-character name plus `_2` must not produce a 32-character username.

    `User.username` is `CharField(30)`. Postgres raises on overflow rather than
    truncating, so getting this wrong is a 500 on the last step of a Google
    sign-up — the point at which the person has already done everything asked.
    """
    long_name = "a" * MAX_LENGTH
    django_user_model.objects.create_user(username=long_name, email="a@x.com", password="pw")

    result = generate_unique_username(long_name)

    assert len(result) <= MAX_LENGTH
    assert result.endswith("_2")


def test_reserved_names_are_never_allocated(django_user_model):
    """A Google account called "Admin" must not become /u/admin."""
    assert generate_unique_username("Admin") != "admin"
    assert generate_unique_username("Admin").startswith("admin_")


def test_deleted_prefix_is_never_allocated():
    """ACC-11 — nobody gets handed a tombstone-shaped handle."""
    assert not generate_unique_username("Deleted 1").startswith("deleted_")


@pytest.mark.parametrize("username", ["ab", "a" * 31, "admin", "deleted_9", "Jeni"])
def test_is_available_rejects(username):
    assert is_available(username) is False


def test_is_available_accepts_a_free_valid_name():
    assert is_available("ananya_iyer") is True
