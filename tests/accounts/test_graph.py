"""Follow and block — the edges, their counters, and the block semantics.

ADR-0002 is the contract being tested. The asymmetry is the point: the `Block`
row is one-way and the effect is not, so almost every case here is asserted in
**both** directions. A view that filters only `blocked` and not `blockers`
passes a naive test and leaks.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from accounts import services
from accounts.models import Block, Follow, Profile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_block_cache():
    """ADR-0003 caches the block set in Redis, keyed per user.

    Without a flush between tests, test B inherits test A's block set and fails
    depending on ordering — the most expensive kind of flake to diagnose
    (`testing.md` §4.2 makes this an autouse fixture globally; it is here too so
    this file stands up before QA's conftest lands).
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="sneha_v", email="s@example.com", password="pw"
    )


def counts(user):
    profile = Profile.objects.get(user=user)
    return profile.follower_count, profile.following_count


# ── Follow ──────────────────────────────────────────────────────────────────


def test_follow_creates_the_edge_and_moves_both_counters(alice, bob):
    services.follow(alice, bob)

    assert Follow.objects.filter(follower=alice, following=bob).exists()
    assert counts(alice)[1] == 1  # alice.following_count
    assert counts(bob)[0] == 1  # bob.follower_count


def test_following_twice_is_idempotent(alice, bob):
    """A double-tap or a retried POST must not double-count."""
    services.follow(alice, bob)
    _, created = services.follow(alice, bob)

    assert created is False
    assert Follow.objects.filter(follower=alice, following=bob).count() == 1
    assert counts(bob)[0] == 1


def test_unfollow_removes_the_edge_and_the_counts(alice, bob):
    services.follow(alice, bob)
    services.unfollow(alice, bob)

    assert not Follow.objects.filter(follower=alice, following=bob).exists()
    assert counts(alice)[1] == 0
    assert counts(bob)[0] == 0


def test_unfollow_when_not_following_is_a_no_op(alice, bob):
    """Must not decrement a counter for an edge that was never there.

    `PositiveIntegerField` is a `CHECK >= 0` in Postgres, so a stray decrement
    at zero is an `IntegrityError` and a 500, not a cosmetic slip.
    """
    assert services.unfollow(alice, bob) is False
    assert counts(bob)[0] == 0


def test_follow_view_requires_post(client, alice, bob):
    client.force_login(alice)
    assert client.get(reverse("accounts:follow", args=[bob.username])).status_code == 405
    assert not Follow.objects.exists()


def test_follow_view_requires_login(client, alice, bob):
    response = client.post(reverse("accounts:follow", args=[bob.username]))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert not Follow.objects.exists()


def test_cannot_follow_yourself(client, alice):
    """Also guarded in the database by `CheckConstraint(~Q(follower=F(following)))`."""
    client.force_login(alice)
    response = client.post(reverse("accounts:follow", args=[alice.username]))
    assert response.status_code == 404
    assert not Follow.objects.exists()


def test_follow_note_attaches_to_an_existing_follow(client, alice, bob):
    services.follow(alice, bob)
    client.force_login(alice)

    client.post(
        reverse("accounts:follow_note", args=[bob.username]),
        {"note": "I'd want the Android role — 2 yrs Kotlin."},
    )

    edge = Follow.objects.get(follower=alice, following=bob)
    assert edge.note == "I'd want the Android role — 2 yrs Kotlin."


def test_follow_note_does_not_create_a_follow(client, alice, bob):
    """If the edge is gone, posting a note must not quietly re-follow."""
    client.force_login(alice)

    client.post(reverse("accounts:follow_note", args=[bob.username]), {"note": "hello"})

    assert not Follow.objects.filter(follower=alice, following=bob).exists()


def test_public_demo_account_cannot_follow(client, django_user_model, bob):
    """ACC-9 — the published-credentials account must not change the graph."""
    demo = django_user_model.objects.create_user(
        username="demo_user",
        email="demo@alongside.app",
        password="pw",
        is_demo=True,
        is_public_demo=True,
    )
    client.force_login(demo)

    client.post(reverse("accounts:follow", args=[bob.username]))

    assert not Follow.objects.exists()
    assert counts(bob)[0] == 0


# ── Block ───────────────────────────────────────────────────────────────────


def test_block_hides_the_profile_in_both_directions(client, alice, bob):
    """The row is one-way; the effect is not (ADR-0002).

    404, never 403 — a 403 confirms the account exists, which tells a blocked
    person exactly what they were trying to find out.
    """
    services.block(alice, bob)

    client.force_login(alice)
    assert client.get(reverse("accounts:profile", args=[bob.username])).status_code == 404

    client.force_login(bob)
    assert client.get(reverse("accounts:profile", args=[alice.username])).status_code == 404


def test_blocked_profile_is_still_public_when_logged_out(client, alice, bob):
    """Deliberate, and pinned so nobody "fixes" it with a login wall.

    Block is a soft barrier scoped to the authenticated experience; the feed is
    public and that is non-negotiable (ADR-0002 "soft barrier", CONTRIBUTING.md rule 7).
    """
    services.block(alice, bob)

    assert client.get(reverse("accounts:profile", args=[bob.username])).status_code == 200


def test_block_deletes_follows_in_both_directions_and_fixes_counters(alice, bob):
    services.follow(alice, bob)
    services.follow(bob, alice)

    services.block(alice, bob)

    assert not Follow.objects.filter(follower__in=(alice, bob)).exists()
    assert counts(alice) == (0, 0)
    assert counts(bob) == (0, 0)


def test_unblock_does_not_restore_follows(alice, bob):
    """ADR-0002 is explicit: they do not come back, the users must re-follow."""
    services.follow(alice, bob)
    services.block(alice, bob)
    services.unblock(alice, bob)

    assert not Follow.objects.filter(follower=alice, following=bob).exists()
    assert counts(bob)[0] == 0


def test_unblock_makes_the_profile_visible_again(client, alice, bob):
    services.block(alice, bob)
    services.unblock(alice, bob)

    client.force_login(alice)
    assert client.get(reverse("accounts:profile", args=[bob.username])).status_code == 200


def test_blocking_takes_effect_within_the_same_request(client, alice, bob):
    """The memo on `request.user` outlives a bare cache delete.

    `blocked_user_ids()` caches on the user instance as well as in Redis, so a
    block created during a request would otherwise render the rest of *that*
    response from the stale set — the page confirming the block would still show
    the blocked person.
    """
    client.force_login(alice)

    client.post(reverse("accounts:block", args=[bob.username]))

    assert Block.objects.filter(blocker=alice, blocked=bob).exists()
    assert client.get(reverse("accounts:profile", args=[bob.username])).status_code == 404


def test_block_requires_post_and_login(client, alice, bob):
    client.force_login(alice)
    assert client.get(reverse("accounts:block", args=[bob.username])).status_code == 405
    assert not Block.objects.exists()

    client.logout()
    response = client.post(reverse("accounts:block", args=[bob.username]))
    assert response.status_code == 302
    assert not Block.objects.exists()


def test_cannot_block_yourself(client, alice):
    client.force_login(alice)
    assert client.post(reverse("accounts:block", args=[alice.username])).status_code == 404
    assert not Block.objects.exists()


def test_public_demo_account_cannot_block(client, django_user_model, bob):
    """ACC-9 — one visitor must not be able to degrade the shared demo account."""
    demo = django_user_model.objects.create_user(
        username="demo_user",
        email="demo@alongside.app",
        password="pw",
        is_demo=True,
        is_public_demo=True,
    )
    client.force_login(demo)

    client.post(reverse("accounts:block", args=[bob.username]))

    assert not Block.objects.exists()


def test_blocked_list_is_not_block_filtered(client, alice, bob):
    """ACC-8 — the one authenticated list where `visible_to()` must NOT apply.

    Filtering it would hide the people it exists to show and leave no way to
    unblock anyone.
    """
    services.block(alice, bob)
    client.force_login(alice)

    response = client.get(reverse("accounts:blocked"))

    assert response.status_code == 200
    assert bob.username in response.content.decode()


def test_unblock_is_reachable_while_the_block_is_active(client, alice, bob):
    """The unblock view deliberately skips the visibility filter.

    Resolving the target the normal way would 404 — which would make a block
    permanent, since the only route out goes through the person you cannot see.
    """
    services.block(alice, bob)
    client.force_login(alice)

    response = client.post(reverse("accounts:unblock", args=[bob.username]))

    assert response.status_code == 302
    assert not Block.objects.exists()


def test_block_does_not_touch_the_blocked_users_own_data(alice, bob):
    """Blocking hides; it never destroys. The equivalent for messages is
    asserted in the Messaging phase, where there must be no delete path at all."""
    bob_profile = Profile.objects.get(user=bob)
    bob_profile.bio = "Product, Chennai."
    bob_profile.save()

    services.block(alice, bob)

    bob.refresh_from_db()
    assert bob.is_active is True
    assert Profile.objects.get(user=bob).bio == "Product, Chennai."


# ── Follower / following lists ──────────────────────────────────────────────


def test_follower_list_hides_block_related_people_from_the_viewer(
    client, django_user_model, alice, bob
):
    """Filtered against the VIEWER's block set, not the profile owner's."""
    carol = django_user_model.objects.create_user(
        username="rohit_k", email="r@example.com", password="pw"
    )
    services.follow(bob, alice)
    services.follow(carol, alice)
    services.block(bob, carol)

    client.force_login(bob)
    response = client.get(reverse("accounts:followers", args=[alice.username]))

    body = response.content.decode()
    assert response.status_code == 200
    assert carol.username not in body
