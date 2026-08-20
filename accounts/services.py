"""Graph and lifecycle operations that must not live in a view.

Everything here writes more than one row, and every one of them has a counter or
a cache entry that has to move in the same transaction. A view that does the
`Follow.objects.create()` itself and forgets the `F()` update is a permanent
drift in a number people see, repaired only by the weekly reconciliation task
(`data-model.md` §7 rule 4) — up to a week of visibly wrong follower counts.

So: **views call these, views never touch `Follow` or `Block` directly.**
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from accounts.blocking import invalidate_block_cache
from accounts.models import Block, Follow, Profile


def _bump(profile_user_id: int, field: str, delta: int) -> None:
    """Move one denormalised counter, atomically, without going negative.

    `Greatest(..., 0)` rather than a plain `F() - 1`: the columns are
    `PositiveIntegerField`, which is a `CHECK >= 0` in Postgres, so decrementing
    a counter that has already drifted to zero raises `IntegrityError` and 500s
    the button (`testing.md` §2.2 calls this out as the bug to chase).
    """
    if delta >= 0:
        value = F(field) + delta
    else:
        value = Greatest(F(field) + delta, 0)
    Profile.objects.filter(user_id=profile_user_id).update(**{field: value})


@transaction.atomic
def follow(follower, following, note: str = "") -> tuple[Follow, bool]:
    """One-way, instant, no approval (spec §2.2, §4.4).

    Returns `(follow, created)`. Idempotent: pressing Follow twice — a
    double-tap, a retried request — must not raise and must not double-count,
    which is what the `UniqueConstraint` and this `get_or_create` are jointly
    for.
    """
    edge, created = Follow.objects.get_or_create(
        follower=follower,
        following=following,
        defaults={"note": note[: Follow._meta.get_field("note").max_length]},
    )
    if created:
        _bump(follower.pk, "following_count", 1)
        _bump(following.pk, "follower_count", 1)
    return edge, created


@transaction.atomic
def unfollow(follower, following) -> bool:
    """Returns whether an edge was actually removed."""
    deleted, _ = Follow.objects.filter(follower=follower, following=following).delete()
    if not deleted:
        return False
    _bump(follower.pk, "following_count", -1)
    _bump(following.pk, "follower_count", -1)
    return True


@transaction.atomic
def block(blocker, blocked) -> tuple[Block, bool]:
    """Full mutual invisibility (ADR-0002).

    Three things happen together, and the ordering matters less than the
    atomicity — a block that half-applies is a safety failure:

    1. The row is created. One direction; the *effect* is symmetric.
    2. Follows in **both** directions are hard-deleted, with both users'
       counters moved (§7.1, ACC-6). Unblocking does not restore them.
    3. Both users' cached block sets are invalidated (ADR-0003 action item 5).

    What deliberately does **not** happen: nothing deletes a `Message` or a
    `Conversation`. Hiding chat is a filter, so unblocking restores the thread
    for free, and there must be no delete path anywhere (ADR-0002).

    Notification cleanup — deleting rows where the other party is `actor` — is
    also required by ADR-0002 but belongs to the Social phase, since the model
    does not exist yet. Tracked in the report rather than silently skipped.
    """
    edge, created = Block.objects.get_or_create(blocker=blocker, blocked=blocked)

    if created:
        _drop_follows_between(blocker, blocked)
        invalidate_block_cache(blocker, blocked)

    return edge, created


@transaction.atomic
def unblock(blocker, blocked) -> bool:
    """Removes the barrier. Does not restore follows — ADR-0002 is explicit."""
    deleted, _ = Block.objects.filter(blocker=blocker, blocked=blocked).delete()
    if deleted:
        invalidate_block_cache(blocker, blocked)
    return bool(deleted)


def _drop_follows_between(a, b) -> None:
    """Hard-delete follow edges in both directions, keeping counters honest."""
    edges = Follow.objects.filter(follower__in=(a, b), following__in=(a, b)).values_list(
        "follower_id", "following_id"
    )

    for follower_id, following_id in list(edges):
        _bump(follower_id, "following_count", -1)
        _bump(following_id, "follower_count", -1)

    Follow.objects.filter(follower__in=(a, b), following__in=(a, b)).delete()


@transaction.atomic
def request_deletion(user) -> None:
    """Start the 30-day grace window (ADR-0001).

    Nothing is scrubbed here — that is the scheduled job's work, and the whole
    point of the window is that this is reversible by logging in
    (`accounts/signals.py`). Idempotent: asking twice must not restart the
    clock, or someone could keep an account alive forever by re-requesting.
    """
    # `get_user_model()`, not `type(user)`: `request.user` is a SimpleLazyObject
    # wrapper, so `type(user)` is that wrapper and has no manager.
    if user.deletion_requested_at is None and user.anonymised_at is None:
        get_user_model().objects.filter(pk=user.pk, deletion_requested_at__isnull=True).update(
            deletion_requested_at=timezone.now()
        )
        user.refresh_from_db(fields=["deletion_requested_at"])


@transaction.atomic
def cancel_deletion(user) -> None:
    """Explicit cancel from Settings. Logging in does the same thing."""
    if user.anonymised_at is not None:
        return
    get_user_model().objects.filter(pk=user.pk, anonymised_at__isnull=True).update(
        deletion_requested_at=None
    )
    user.deletion_requested_at = None
