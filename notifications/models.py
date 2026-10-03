"""Notifications — the return loop.

Owned by the Architect (`CLAUDE.md` rule 2). The Builder seat reads and writes this
table (bell count, Alerts screen, fan-out on comment and follow) and does not edit
this file. Schema changes go seat → Jeni → Architect → `docs/data-model.md` →
migration.

Contents follow `data-model.md` §5, as amended by the Social seat's review
(`docs/review/social.md`, findings S4–S10). Where a review or a ruling changed
something, the finding id is cited inline so the reasoning is one grep away.

Three things about this app are different from every other model in the project,
and all three are deliberate:

1. **No `ActiveManager` split.** `Post`, `Comment` and `Message` are soft-deleted
   and therefore carry `deleted_at` plus a two-manager split (§8.2). Notifications
   are **hard**-deleted (§8) — they carry no evidential value, the content they
   point at survives for moderation on its own row, and a 90-day prune keeps this
   from becoming the biggest table in the database. So there is no `deleted_at`
   here, no `all_objects`, and nothing to filter. `objects` is the only manager.
2. **`visible_to()` filters on `actor`, not an author** (S9). See
   `NotificationQuerySet`.
3. **Rows are deleted when their target is soft-deleted** (S8, Jeni's ruling). The
   FKs below are `CASCADE`, but CASCADE never fires for a soft delete — the
   deleting code does it explicitly. See the note on `post` / `comment`.

**`new_message` and the `conversation` FK are not here yet.** `messaging` 0001
cannot be finalised while Jeni's decision E is open (§12.4), so there is no
`messaging.Conversation` to point a foreign key at and `notifications` 0001 cannot
depend on a migration that does not exist. Phase 4 ships `new_comment` and
`new_follower`; `new_message`, the `conversation` FK and the S4 unread-DM unique
constraint all land together in `notifications` 0002 alongside `messaging` 0001.
The `notification_kind_targets` check constraint below is what stops a
`new_message` row being written in the meantime — see its comment.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from accounts.blocking import BlockAwareQuerySetMixin
from posts.models import Comment, Post

# Dedup window for rule 1 (§5.2). A **double-submit guard, not a burst guard**.
#
# That rule 1 and rule 2 differ in kind is the **Builder seat's reading of §5.2
# (S6), and it is awaiting Jeni's confirmation** — she has not ruled on it. The
# reading: five comments from one person over an hour is five things to read and
# should produce five notifications, whereas two comments 200ms apart is one person
# double-tapping Submit; rule 2 is a burst guard by design, because ten messages in
# one conversation is one thing to know about. Until there is a ruling, do not
# "fix" the asymmetry in either direction — collapsing rule 1 into a burst guard,
# or widening rule 2, is a product change and goes seat → Jeni → Architect.
#
# Lives here rather than in `social/services.py` so the fan-out code, the tests and
# the seed all read the same number — the same reason the `MAX_*` caps live in
# `posts.models`.
COMMENT_NOTIFICATION_DEDUP_WINDOW = timedelta(seconds=60)


class NotificationKind(models.TextChoices):
    """The triggers that exist. Spec §4.6 lists exactly three.

    `NEW_MESSAGE = "new_message"` is the third and is **absent on purpose** until
    the `conversation` FK exists (see the module docstring). Adding it is one line
    here, one `AlterField`, and one rewritten check constraint in 0002.

    There is deliberately **no `new_spark`** ✅ (§9 Q9). Sparks are a stranger's one
    click; notifying on them is noise, and notifications are the retention engine,
    so a noisy bell is a product failure rather than a cosmetic one.
    """

    NEW_COMMENT = "new_comment", _("New comment")
    NEW_FOLLOWER = "new_follower", _("New follower")


class NotificationQuerySet(BlockAwareQuerySetMixin, models.QuerySet):
    # `actor` (S9). ADR-0003 originally said `.exclude(<author field>__in=…)`, and
    # on this model the naive reading gives **no field at all** — there is nothing
    # called "author" here. The actor is the person whose content is being surfaced
    # (commenter, follower, sender) for every kind, so excluding on it is both
    # necessary and sufficient; the Social review checked that no notification
    # survives a block while still exposing blocked content, so nothing else needs
    # filtering here.
    #
    # ADR-0002 already *deletes* rows where the other party is the actor at block
    # time. This is the second line of defence the ADR asks for: deletion is a
    # one-shot write that can be missed or lost to a failed transaction, while the
    # filter holds on every read.
    block_filter_field = "actor"


class Notification(models.Model):
    """One entry in the bell and on the Alerts screen (screen 12).

    Concrete nullable FKs rather than a `GenericForeignKey`: the target types are
    three, known, and closed. Concrete FKs give
    `select_related("actor", "post", "comment")` — one query for the whole bell
    dropdown — while a `GenericForeignKey` cannot be `select_related`ed and produces
    an N+1 by construction on a surface that renders on every authenticated page.
    """

    # ── Who ──────────────────────────────────────────────────────────────────
    #
    # `db_index=False`: the `notification_recipient_idx` composite below leads with
    # `recipient`, so the index Django would create for this FK is a strict prefix
    # of one we already build — write amplification on the app's highest-insert
    # table for nothing. Same reasoning as ACC-4, which dropped four indexes for
    # being duplicates of an FK's own; this is the mirror case. Postgres needs no
    # index on the referencing side for referential integrity, and the CASCADE on
    # user deletion finds its rows through the composite's leading column.
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=False,
    )
    # Nullable so a future system-generated kind (Designer's GAP 13 `stale_nudge`
    # is the obvious candidate) needs no migration on this column. Every kind that
    # exists today has a real person as its actor, which the check constraint
    # enforces per kind — see `notification_kind_targets`.
    #
    # Index kept (unlike `recipient`): no composite leads with `actor`, and
    # anonymisation and account deletion both sweep by actor.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications_sent",
        null=True,
        blank=True,
    )

    # ── What ─────────────────────────────────────────────────────────────────
    kind = models.CharField(_("kind"), max_length=20, choices=NotificationKind.choices)

    # ── The target ───────────────────────────────────────────────────────────
    #
    # Both FKs are CASCADE, and **CASCADE never fires** for either of them: posts
    # and comments are SOFT-deleted (§8), so the row they point at is still there.
    # Left alone, that is S8: the bell renders an entry linking to content that is
    # gone, and if the entry is unread it inflates the count permanently for
    # something that will never be there.
    #
    # **Jeni's ruling (S8): hard-delete the notification when its post or comment is
    # soft-deleted.** The schema half is these FKs and their indexes; the write is
    # the Builder seat's, in `social/services.py`, in the same `transaction.atomic()`
    # block as the soft delete and as the `comment_count` decrement §7.1 already
    # requires:
    #
    #     Notification.objects.filter(comment=comment).delete()   # soft_delete_comment()
    #     Notification.objects.filter(post=post).delete()         # post soft delete
    #
    # The post sweep covers that post's `new_comment` rows too, because every one of
    # them carries `post` as well as `comment`.
    #
    # The FK's own index is what makes those two queries lookups rather than scans,
    # so neither FK sets `db_index=False`.
    #
    # **Undelete does not restore them** — they are hard-deleted and gone. That is
    # the one place this rule does not mirror §7.1's counter rules, which all
    # reverse cleanly. Recorded in §7.1 so it reads as a known cost rather than a
    # bug: an undeleted comment is visible again, nobody is re-notified about it.
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    # `conversation` FK → `messaging.Conversation` lands in `notifications` 0002.
    # See the module docstring for why it cannot land here.

    # ── State ────────────────────────────────────────────────────────────────
    #
    # Load-bearing, not cosmetic. Both dedup rules key on `is_read=False`, so "Mark
    # all read" is the mechanism that lets the *next* burst create a fresh
    # notification instead of being collapsed into a row the user has already seen.
    # Anyone adding a separate "seen" concept later must not repoint the dedup rules
    # at it without re-deriving §5.2.
    is_read = models.BooleanField(_("read"), default=False)

    # `auto_now_add`, and that is the S4 footgun worth stating out loud: **bumping
    # `created_at` for a collapsed notification works only through
    # `QuerySet.update()`.** `auto_now_add` sets the column on INSERT and is
    # ignored on UPDATE, so a `.save()`-based bump silently does nothing and the
    # collapsed notification sorts to the bottom of the bell — exactly the row the
    # user most needs at the top. The dedup path is therefore
    # `.update(created_at=Now(), ...)`, never load-mutate-save.
    #
    # `db_index=True` is not covered by the two indexes below, both of which lead
    # with `recipient`: the 90-day prune job (§8) scans the whole table by age, so
    # it needs an index that leads with `created_at`.
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        # No `Meta.ordering` (ACC-14). A default ordering leaks into joins,
        # subqueries and aggregates, not just the queries that want it — and the
        # bell count is an aggregate that runs on every authenticated page load.
        constraints = [
            # Never notify yourself. `actor` is nullable and Postgres treats a
            # comparison against NULL in a CHECK as passing, so a future
            # system-generated row with no actor satisfies this for free. That is
            # deliberate (S7): do **not** "harden" this into rejecting null actors.
            models.CheckConstraint(
                condition=~Q(recipient=F("actor")),
                name="notification_not_self",
            ),
            # S7 — tie `kind` to the FKs it needs. Without this, a `new_follower`
            # row with a stray `post_id` or a `new_comment` with `comment = NULL` is
            # legal, and the bell dereferences the FK that matches `kind` on every
            # page load: a null there is a blank row at best and a 500 at worst, on
            # the one surface that renders for every logged-in user on every page.
            # §6.1 already does exactly this for `Report`.
            #
            #   kind           | required            | must be null
            #   ---------------+---------------------+---------------------------
            #   new_comment    | comment, post, actor| (conversation, in 0002)
            #   new_follower   | actor               | post, comment (+ conversation)
            #
            # `new_comment` requires `post` as well as `comment` because the Alerts
            # row reads "<b>X</b> commented on <b>your bike-repair log idea</b>" —
            # it needs the post's title, and reaching it via `comment.post` is a
            # second join on a list query that `select_related("post")` already
            # covers. It is also what makes the post-level sweep in the S8 rule
            # above sufficient on its own.
            #
            # `actor` is required by both branches, which goes one step beyond S7's
            # table: both kinds render the actor's name in bold as the subject of
            # the sentence, so a null actor is the same unrenderable row S7 is
            # about. It does not conflict with `notification_not_self` tolerating
            # nulls — the first kind with a genuinely null actor (`stale_nudge`)
            # simply adds its own branch here, which this constraint has to be
            # rewritten for anyway.
            #
            # **This is also what keeps `new_message` out of the table until 0002.**
            # The branches are exhaustive by construction: any `kind` value that is
            # not listed fails the whole condition, so the database rejects a
            # `new_message` row outright. `choices` could not do that — it is
            # validated in forms and `full_clean()` only, and the fan-out path is
            # `objects.create()`, which never calls it. Without this constraint a
            # mis-aimed Phase 5 branch could write rows that the Alerts template
            # has no case for, and they would sit in the unread count forever.
            models.CheckConstraint(
                condition=(
                    Q(
                        kind=NotificationKind.NEW_COMMENT,
                        actor__isnull=False,
                        post__isnull=False,
                        comment__isnull=False,
                    )
                    | Q(
                        kind=NotificationKind.NEW_FOLLOWER,
                        actor__isnull=False,
                        post__isnull=True,
                        comment__isnull=True,
                    )
                ),
                name="notification_kind_targets",
            ),
            # S5, ruled yes by Jeni: collapse repeat follows, same shape as the DM
            # rule. Follow is one-way, instant and freely toggleable (§1.4), so
            # follow → unfollow → follow from one person would otherwise produce N
            # bell entries and bury everything else the user has. `django-ratelimit`
            # lowers the ceiling; it does not make it one notification.
            #
            # A *partial* unique index, so it costs almost nothing and scopes itself
            # away from the other kinds: it only constrains unread `new_follower`
            # rows. Once the user reads (or "Mark all read"s) the row, the next
            # follow from the same person is a fresh notification, which is right.
            #
            # The constraint is the point, not the convenience: the documented rule
            # is read-then-write, and two workers racing both see zero unread rows
            # and both insert — in exactly the burst the rule exists to prevent.
            # With the index underneath, the Builder's fan-out is structurally
            # correct rather than hopefully correct:
            #
            #     updated = Notification.objects.filter(
            #         recipient=recipient, actor=actor,
            #         kind=NotificationKind.NEW_FOLLOWER, is_read=False,
            #     ).update(created_at=Now())
            #     if not updated:
            #         try: ... create ...
            #         except IntegrityError: ... re-run the update ...
            #
            # Name kept verbatim from `docs/review/social.md` S5 so the review and
            # the schema match on a grep.
            models.UniqueConstraint(
                fields=["recipient", "actor"],
                condition=Q(kind=NotificationKind.NEW_FOLLOWER, is_read=False),
                name="uniq_unread_follow_notification_per_actor",
            ),
            # The S4 twin — `UniqueConstraint(recipient, conversation)` where
            # `kind="new_message" AND is_read=false` — lands in 0002 with the
            # `conversation` FK. It cannot be written here: there is no column to
            # put it on.
        ]
        indexes = [
            # The Alerts screen (screen 12), newest first.
            models.Index(fields=["recipient", "-created_at"], name="notification_recipient_idx"),
            # The bell count, which runs on **every authenticated page load**. A
            # partial index here is the difference between a scan of the recipient's
            # whole notification history and a lookup over only the handful of rows
            # that are actually unread — and the unread set is small and stays small
            # while the full set grows for 90 days.
            #
            # It is also the index behind the unique constraint's sibling lookups:
            # both dedup rules filter on `is_read=False`.
            #
            # Shape is `(recipient)` exactly as §5.1 specifies. The Alerts screen's
            # "New" group wants `(recipient, -created_at)` partial to sort as well
            # as filter; at v1 scale the unread set per user is a few rows, so the
            # sort is free and widening this index is not worth a deviation from the
            # approved document. If the Alerts query ever shows up in a real
            # `EXPLAIN`, adding `-created_at` here is a one-line migration.
            models.Index(
                fields=["recipient"],
                condition=Q(is_read=False),
                name="notification_unread_idx",
            ),
        ]

    def __str__(self):
        return f"{self.kind} for {self.recipient_id}"
