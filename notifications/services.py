"""Fan-out — the only place a `Notification` row is written or deleted.

Notifications are the return loop (roadmap §1.3): without them the place is a
ghost town, and a noisy bell is a product failure rather than a cosmetic one
(spec §8). That makes the dedup rules in `data-model.md` §5.2 load-bearing, and
they are the whole reason this module exists instead of three
`Notification.objects.create()` calls spread across two apps.

Three triggers in v1 — new comment, new follower, new DM — and `new_message`
is Phase 5, so there are two here. **Sparks deliberately generate nothing**
(§2.7): a spark is a stranger's one click, and spark notifications are noise.

Everything here is a no-op rather than an error when there is nothing to do.
Fan-out hangs off a user action that has already succeeded — the comment is
written, the follow edge exists — so a notification that cannot be created must
never take the action down with it.
"""

from django.db import IntegrityError, transaction
from django.db.models.functions import Now
from django.utils import timezone

from notifications.models import (
    COMMENT_NOTIFICATION_DEDUP_WINDOW,
    Notification,
    NotificationKind,
)


# ── Creating ────────────────────────────────────────────────────────────────


def notify_new_comment(comment) -> Notification | None:
    """Tell the post's author somebody commented.

    Dedup rule 1 (§5.2): no second `new_comment` for the same post from the same
    actor within 60 seconds. That is a **double-submit guard, not a burst
    guard** — five comments over an hour is five things to read, and
    deliberately produces five notifications (S6, awaiting Jeni's confirmation).

    Unlike the follower rule there is no unique constraint underneath this one,
    because the condition is a time window rather than a state: two requests
    200ms apart can both pass the check and create two rows. That is the
    accepted ceiling for a guard against a double-tapped Submit button — the
    cost is one duplicate bell entry in a rare race, and the alternative is a
    constraint on a moving target.

    Returns `None` when nothing was created, including the self-comment case:
    commenting on your own idea notifies nobody, which the
    `notification_not_self` check constraint would reject anyway.
    """
    recipient = comment.post.author
    actor = comment.author

    if recipient.pk == actor.pk:
        return None

    since = timezone.now() - COMMENT_NOTIFICATION_DEDUP_WINDOW
    already = Notification.objects.filter(
        recipient=recipient,
        actor=actor,
        post=comment.post,
        kind=NotificationKind.NEW_COMMENT,
        created_at__gte=since,
    ).exists()
    if already:
        return None

    # `post` AND `comment`, both required by `notification_kind_targets`: the
    # Alerts row reads "X commented on your bike-repair log idea", so it needs
    # the post's title without a second join.
    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        kind=NotificationKind.NEW_COMMENT,
        post=comment.post,
        comment=comment,
    )


def notify_new_follower(follower, following) -> Notification | None:
    """Tell somebody they have a new follower.

    Dedup rule for follows, ruled in by Jeni (S5): don't create a second
    **unread** `new_follower` from the same actor — bump the existing row
    instead. Follow is one-way, instant and freely toggleable (§1.4), so without
    this, follow → unfollow → follow from one person produces N bell entries and
    buries everything else the recipient has.

    Written update-first, create-on-zero-rows, catch-and-re-update, which is the
    shape the partial `UniqueConstraint` makes **structurally** correct rather
    than hopefully correct: two workers racing both see zero unread rows, both
    insert, and the loser's `IntegrityError` is handled instead of 500ing a
    follow that already succeeded.

    `.update()`, never load-mutate-save: `created_at` is `auto_now_add`, which is
    set on INSERT and ignored on UPDATE, so a `.save()` bump silently does
    nothing and the collapsed notification sorts to the *bottom* of the bell —
    the one row the user most needs at the top (the S4 footgun).
    """
    if follower.pk == following.pk:
        return None

    unread = Notification.objects.filter(
        recipient=following,
        actor=follower,
        kind=NotificationKind.NEW_FOLLOWER,
        is_read=False,
    )

    if unread.update(created_at=Now()):
        return None

    try:
        with transaction.atomic():
            return Notification.objects.create(
                recipient=following,
                actor=follower,
                kind=NotificationKind.NEW_FOLLOWER,
            )
    except IntegrityError:
        # Somebody else inserted the unread row between the update and the
        # insert. Bump theirs; the user wanted one notification and has one.
        unread.update(created_at=Now())
        return None


def notify_new_message(recipient, actor, conversation) -> Notification | None:
    """Tell somebody they have a new DM. Dedup rule 2 (§5.2) — the important one.

    Unlike the comment rule, this **is** a burst guard, and deliberately so: ten
    messages in one conversation is one thing the user needs to know about, not
    ten. Without it, a burst produces ten bell entries and buries every other
    notification they have. That was the rule missing from the first draft of
    the data model, and the Social review called it the more important of the
    two.

    Update-first, create-on-zero-rows, catch-and-re-update — the same shape as
    the follow rule, made structurally correct rather than hopefully correct by
    the S4 partial unique constraint. In a message burst, two workers racing
    both see zero unread rows and both insert; in exactly the scenario the rule
    exists to prevent.

    `.update()`, never load-mutate-save: `created_at` is `auto_now_add`, so a
    `.save()` bump silently does nothing and the collapsed notification sorts to
    the bottom of the bell.
    """
    if recipient.pk == actor.pk:
        return None

    unread = Notification.objects.filter(
        recipient=recipient,
        conversation=conversation,
        kind=NotificationKind.NEW_MESSAGE,
        is_read=False,
    )

    if unread.update(created_at=Now()):
        return None

    try:
        with transaction.atomic():
            return Notification.objects.create(
                recipient=recipient,
                actor=actor,
                kind=NotificationKind.NEW_MESSAGE,
                conversation=conversation,
            )
    except IntegrityError:
        unread.update(created_at=Now())
        return None


def notify_stale_nudge(post) -> Notification | None:
    """Ask a post's author whether they are still looking (TS-2 / Designer GAP 13).

    The one notification kind with **no actor**: nothing did this, the system
    noticed. `notification_not_self` tolerates a null actor for exactly this
    case, and `notification_kind_targets` gives `stale_nudge` its own branch
    requiring `post` and forbidding an actor — so a row that claims a person
    sent it cannot be written.

    No dedup rule and no constraint behind it, unlike every other kind. The job
    sets `nudged_at` and only selects posts where it is NULL, so the candidate
    query is itself the guard: one nudge per post per stale cycle.

    The Alerts screen renders this as a warning banner with "Yes, still
    looking" and "Team formed" — the two buttons are the whole point, because a
    nudge nobody can answer is just a worse way of demoting somebody.
    """
    return Notification.objects.create(
        recipient=post.author,
        actor=None,
        kind=NotificationKind.STALE_NUDGE,
        post=post,
    )


# ── Deleting ────────────────────────────────────────────────────────────────
#
# Notifications are the one model in the project that is HARD-deleted (§8), plus
# a job pruning read rows older than 90 days. They carry no evidential value —
# the comment or post itself survives on its own row for moderation, which is
# the only thing a report needs.


def drop_for_comment(comment) -> int:
    """Delete the notifications pointing at a comment that is being removed.

    S8, ruled by Jeni: `Notification.comment` is CASCADE, and **CASCADE never
    fires** for a soft delete, so without this the bell keeps an entry linking
    to a comment that is gone — and if the entry is unread it inflates the count
    permanently for something that will never be there.

    Called from `social.services.soft_delete_comment()` inside the same
    transaction as the soft delete and the `comment_count` decrement.

    **Undelete does not restore these.** Every other rule in §7.1 reverses
    cleanly and this one does not: an undeleted comment is visible again and
    nobody is re-notified about it. That is the accepted cost of the cheapest
    correct answer.
    """
    deleted, _ = Notification.objects.filter(comment=comment).delete()
    return deleted


def drop_for_post(post) -> int:
    """Same rule, one level up — for a post being soft-deleted.

    This covers that post's `new_comment` notifications too, because
    `notification_kind_targets` requires every one of them to carry `post` as
    well as `comment`. Posts & Feed calls this when it wires post deletion.
    """
    deleted, _ = Notification.objects.filter(post=post).delete()
    return deleted


def drop_between(user_a, user_b) -> int:
    """Delete notifications where either party is the other's actor.

    ADR-0002: blocking is full mutual invisibility, and that includes the bell.
    `accounts/services.py::block()` recorded this as Social-phase work because
    the model did not exist when it was written.

    Both directions, because the `Block` row is one-way and the effect is not.
    `visible_to()` filters the bell on `actor` as well (S9) — this delete is the
    permanent half, the filter is the half that still holds if a delete is ever
    missed or lost to a failed transaction.
    """
    deleted, _ = Notification.objects.filter(
        recipient__in=(user_a, user_b), actor__in=(user_a, user_b)
    ).delete()
    return deleted


# ── Reading ─────────────────────────────────────────────────────────────────


def mark_all_read(user) -> int:
    """"Mark all read" on the Alerts screen. Returns how many moved.

    This is also the mechanism that lets the *next* burst through: both dedup
    rules key on `is_read=False`, so a collapsed notification stops collapsing
    once the user has seen it, and the follow after that is a fresh entry rather
    than a silent bump to a row they already read.
    """
    updated = Notification.objects.filter(recipient=user, is_read=False).update(is_read=True)
    return updated


def unread_count(user) -> int:
    """The bell badge. Runs on **every authenticated page load** (§5.1).

    `notification_unread_idx` is partial on exactly this predicate, so it is a
    lookup over the handful of unread rows rather than a scan of a 90-day
    history. `visible_to()` is applied because a blocked actor's notification
    must not be counted even in the window before the delete lands.
    """
    return Notification.objects.visible_to(user).filter(recipient=user, is_read=False).count()
