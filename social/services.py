"""Engagement writes — every one of them moves a counter.

Three of the four toggles in this app write two rows: the edge itself and the
denormalised counter that the feed sorts on. `data-model.md` §7 says *how* to
move a counter (`F()` expressions, atomic, never below zero) and the Social
seat's review (S3) pinned down *when*:

> Only adjust a counter when the underlying row was actually created or actually
> deleted. `created=False` from `get_or_create`, a caught `IntegrityError`, and a
> delete returning `0` are all no-ops for the counter.

That is the rule the views could not be trusted to each remember, so it lives
here once and **views never write `PostSpark`, `CommentSpark`, `SavedPost` or
`Comment` directly** — the same contract `accounts/services.py` holds for
`Follow` and `Block`.

The double-tap case is not theoretical. Two taps on a phone arrive as two
requests, and an `exists()`-then-`create()` toggle loses that race: both see no
row, both insert, one gets an `IntegrityError` and the user gets a 500 on the
signature control of the product. Every toggle here catches it in a nested
`atomic()` block and treats it as "already on", because that is what it is.
"""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest, Now

from posts.models import Comment, CommentSpark, Post, PostSpark, SavedPost


def _bump(model, pk: int, field: str, delta: int) -> None:
    """Move one counter on one row, atomically, without going below zero.

    `Greatest(..., 0)` rather than a bare `F() - 1`: these are
    `PositiveIntegerField`s, i.e. a `CHECK >= 0` in Postgres, so decrementing a
    counter that has already drifted to zero is an `IntegrityError` and a 500 on
    the button — not a cosmetic slip.

    Always `all_objects` where the model has one. A spark or a comment can
    legitimately be removed from a soft-deleted post (a moderator working the
    queue), and the default manager would filter that row out and silently skip
    the counter.
    """
    manager = getattr(model, "all_objects", model.objects)
    value = F(field) + delta if delta >= 0 else Greatest(F(field) + delta, 0)
    manager.filter(pk=pk).update(**{field: value})


# ── Sparks ──────────────────────────────────────────────────────────────────


@transaction.atomic
def toggle_post_spark(user, post) -> bool:
    """Spark or un-spark a post. Returns the state the user is now in."""
    deleted, _ = PostSpark.objects.filter(user=user, post=post).delete()
    if deleted:
        _bump(Post, post.pk, "spark_count", -1)
        return False

    try:
        with transaction.atomic():
            PostSpark.objects.create(user=user, post=post)
    except IntegrityError:
        # A concurrent duplicate — the second tap of a double-tap. The row the
        # user wanted exists, so the answer is "sparked" and the counter was
        # already moved by whoever won.
        return True

    _bump(Post, post.pk, "spark_count", 1)
    return True


@transaction.atomic
def toggle_comment_spark(user, comment) -> bool:
    """Same contract, on a comment. Sparks on comments are in v1 (spec §4.4)."""
    deleted, _ = CommentSpark.objects.filter(user=user, comment=comment).delete()
    if deleted:
        _bump(Comment, comment.pk, "spark_count", -1)
        return False

    try:
        with transaction.atomic():
            CommentSpark.objects.create(user=user, comment=comment)
    except IntegrityError:
        return True

    _bump(Comment, comment.pk, "spark_count", 1)
    return True


# ── Save ────────────────────────────────────────────────────────────────────


@transaction.atomic
def toggle_save(user, post) -> bool:
    """Bookmark or un-bookmark. Private — never visible to anyone else.

    `save_count` is in §7's list of denormalised counters and was not being
    moved anywhere: the first version of the save endpoint wrote the `SavedPost`
    row and stopped. Nothing renders the number yet, which is exactly why it
    would have been found months later as unexplained drift in the one counter
    with no screen to check it against.
    """
    deleted, _ = SavedPost.objects.filter(user=user, post=post).delete()
    if deleted:
        _bump(Post, post.pk, "save_count", -1)
        return False

    try:
        with transaction.atomic():
            SavedPost.objects.create(user=user, post=post)
    except IntegrityError:
        return True

    _bump(Post, post.pk, "save_count", 1)
    return True


# ── Comments ────────────────────────────────────────────────────────────────


@transaction.atomic
def add_comment(author, post, body: str) -> Comment:
    """Write a comment, move the count, and bring the post back to life.

    `touch_activity()` is the part that is easy to miss and expensive to lose.
    It is the only writer of `last_activity_at` and the only thing that clears
    `is_stale`, and it is deliberately cross-seat (`posts/models.py`): Social
    bumps it on comment, Posts on edit, Trust & Safety on a nudge reply. Without
    the call here, a post that just collected five comments still reads as
    abandoned and stays demoted to the bottom of every feed.
    """
    comment = Comment.objects.create(post=post, author=author, body=body)
    _bump(Post, post.pk, "comment_count", 1)
    post.touch_activity()

    # One of the three triggers in spec §4.6, and the reason the bell is the
    # return loop rather than a decoration. Imported here rather than at module
    # level to keep `social` → `notifications` from becoming a load-time edge
    # between two apps that otherwise do not know about each other.
    from notifications import services as notification_services

    notification_services.notify_new_comment(comment)

    return comment


@transaction.atomic
def soft_delete_comment(comment) -> bool:
    """The only correct way to remove a comment (S12). Returns whether it moved.

    Comments are soft-deleted because a deleted one may still be attached to an
    open report (§8) — and the decrement has to ride along in the same
    transaction. Setting `deleted_at` directly, from a view or from Django
    admin, leaves `Post.comment_count` one too high: the post then reads "12
    comments" above 11 rendered rows, which looks like a caching bug and isn't.

    **Trust & Safety and the admin call this, not `deleted_at`.**

    The guard is in the `UPDATE`, not in Python: two delete requests for the same
    comment both see `deleted_at IS NULL`, and only the one that actually wrote
    the row may touch the counter.
    """
    updated = Comment.all_objects.filter(pk=comment.pk, deleted_at__isnull=True).update(
        deleted_at=Now()
    )
    if not updated:
        return False

    _bump(Post, comment.post_id, "comment_count", -1)

    # S8, ruled by Jeni: the notification goes with it. `Notification.comment`
    # is CASCADE and CASCADE never fires for a soft delete, so without this the
    # bell keeps an entry pointing at a comment that is gone — and an unread one
    # inflates the badge permanently for something that will never be there.
    # Undeleting does not bring the notification back; §7.1 records that.
    from notifications import services as notification_services

    notification_services.drop_for_comment(comment)

    return True
