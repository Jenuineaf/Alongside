"""Messaging models — the conversation, its participants, and the messages in it.

Owned by the Architect (`CONTRIBUTING.md` rule 2). The **Builder seat** owns the chat UI,
the conversation list, the send path and the creation chokepoint described below, and
reads and writes these tables; it does not edit this file. Schema changes go
seat → Jeni → Architect → `docs/data-model.md` → migration.

Contents follow `data-model.md` §4, as amended by the Messaging seat's review
(`docs/review/messaging.md`, M2–M5 and M11–M17) and the Designer's GAP 11
(`docs/review/designer.md`). Where a review or a ruling changed something, the
finding id is cited inline so the reasoning is one grep away.

**Two of Jeni's decisions closed on 4 Oct 2026, and both land here.**

*Decision E — a NUMBER, not a dot* (§12.4, M2 / M6). So `ConversationParticipant`
carries `unread_count` and the partial index M2 costed. This is the decision that was
blocking `messaging` 0001 — it was the only open question that changed a column, which
is why nothing in this app could be written while it was open. The Designer's
`components/_tab_bar.html` already renders a numeric badge, so the built UI and the
schema now agree rather than one of them being retrofitted.

*GAP 11 — yes, `Conversation.origin_post`*. The Designer called it the biggest gap in
the whole review and the Messaging seat seconded it (M5). The product is "find an idea
→ message the person", and anyone can DM anyone with no request gate, so the
receiver's first question is always *why is this person messaging me* — and every
screen the Designer drew answers it with a context strip. See the field for the
`dyad_key` conflict M5 raised and how the ruling resolves it.

Three things about this app differ from its neighbours, and all three are deliberate:

1. **Only `Message` is soft-deleted.** It carries `deleted_at` plus the two-manager
   split §8.2 describes. `Conversation` and `ConversationParticipant` do **not** —
   blocking hides a thread with a filter rather than deleting it (ADR-0002), so there
   is nothing to soft-delete and unblock restores the thread with no restore code path
   at all. Note this is the **opposite** of `Notification` and `Report`: notifications
   are hard-deleted (§8) and a report carries no `deleted_at` because it *is* the
   evidence that justifies everyone else's, so neither of those models has an
   `ActiveManager` / `all_objects` split and this one does.
2. **`Conversation.visible_to()` filters on `participants__user`** (M15), and
   **`Message` deliberately has no `visible_to()` at all.** See `MessageQuerySet`.
3. **The denormalised fields on `Conversation` are written as one transaction** —
   see the write contract on the model.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from accounts.blocking import BlockAwareQuerySetMixin
from posts.models import Post

# Form-level cap, same convention as `posts.models` and `moderation.models` and for
# the same reason: §0 says `TextField(N)` is enforced in forms only and never in
# Postgres, and the number lives on the model so the form, the DRF serializer, the
# tests and the seed all read one value. A test that pushes 9000 characters through
# the ORM will succeed, by design.
MAX_MESSAGE_LENGTH = 4000

# This one IS a database limit — `last_message_preview` is a `CharField`, so Postgres
# enforces it. The send path truncates to it; it does not rely on the column to.
PREVIEW_LENGTH = 140

# `dyad_key` sizing, kept next to the formatter that produces it.
DYAD_KEY_WIDTH = 19
DYAD_KEY_MAX_LENGTH = 40


def dyad_key_for(user_a_id, user_b_id) -> str:
    """The canonical `dyad_key` for a pair of users. **The only place it is formatted.**

    M11 — §4.1 writes the key as `"{min_id}:{max_id}"`, and that is
    ordering-independent only if `min` / `max` run on **integers**. `min(9, 10)` is
    `9`; `min("9", "10")` is `"10"`. A string-sorted implementation therefore writes
    `"10:9"` for one caller and `"9:10"` for the other, **both inserts succeed**, and
    you get exactly the duplicate thread the unique constraint exists to prevent. It
    passes every test with ids 1-9 and starts failing the moment ids cross a digit
    boundary — roughly where QA's ~20 seeded users land.

    Zero-padding to 19 digits (`BigAutoField`'s maximum) makes the key correct under
    **both** numeric and lexical sort, so it cannot be implemented wrongly. Worst case
    is 19 + 1 + 19 = 39 characters, one spare inside `CharField(40)`.

    Raises `ValueError` on a self-DM (M12). Nothing prevents `dyad_key = "5:5"` at the
    database level and it **cannot** be a `CheckConstraint` the way `Follow` and
    `Block` each have one — the participants live in another table — so the guard goes
    in the formatter every caller has to pass through.
    """
    a, b = int(user_a_id), int(user_b_id)
    if a == b:
        raise ValueError("A conversation needs two different participants (M12).")
    return f"{min(a, b):0{DYAD_KEY_WIDTH}d}:{max(a, b):0{DYAD_KEY_WIDTH}d}"


class ConversationQuerySet(BlockAwareQuerySetMixin, models.QuerySet):
    # `participants__user` (M15). ADR-0003 originally said
    # `.exclude(<author field>__in=…)` and listed `Conversation` among the models
    # receiving it — but a conversation **has no author field**, so the generic
    # reading cannot apply here. It would not have surfaced as an error either; it
    # would have surfaced as somebody writing something plausible.
    #
    # The mixin's `.exclude()` (never `.filter(~Q(...))`) is load-bearing on this
    # model specifically, because the path is multi-valued: `exclude()` builds a
    # subquery and drops the conversation if **any** participant is blocked, while
    # `filter(~Q())` negates per joined row and lets the conversation straight back in
    # via the other participant's row. That is a silent leak in the one place ADR-0002
    # cares most about. The reasoning lives in `accounts/blocking.py`; it is repeated
    # here because this is the model where getting it wrong is worst.
    block_filter_field = "participants__user"


class Conversation(models.Model):
    """One thread. 1:1 in v1, with the door left open for group chat.

    **The write contract for the denormalised fields** (M4, M14, M16). Every send
    updates `last_message_at` and `last_message_preview` in the **same**
    `transaction.atomic()` block as the `Message` insert, together with the sender's
    own `ConversationParticipant.last_read_at` and every *other* participant's
    `unread_count`. Fields that can drift independently are chances to drift, and the
    §7 rule-4 weekly reconciliation job covers these the same way it covers counters.

    One case the send path does not cover, and M16 names it: **soft-deleting the
    newest message leaves the preview rendering deleted text on the conversation
    list.** The recompute (newest surviving message, or a tombstone) is the Builder's,
    recorded in §7.1 so it is a known rule rather than a rediscovered bug.
    """

    # ── The duplicate-thread guard ───────────────────────────────────────────
    #
    # `unique=True` **is** the index §4.1 asks for — a unique constraint is a btree in
    # Postgres — so there is no `db_index=True` here. Adding it would build a second
    # index over the same column, which is the ACC-4 mistake in mirror image.
    #
    # Nullable by design: in Postgres NULLs do not collide in a unique index, so any
    # number of future group conversations can carry `dyad_key = NULL` with no schema
    # change. The consequence M12 names is not free, though — **the constraint
    # protects only rows that remember to set the key.** A `Conversation()` built
    # anywhere without one creates a silent duplicate and raises nothing. So the
    # guarantee is really the constraint *plus* one chokepoint: **all 1:1 creation
    # goes through a single `get_or_create`-style helper in the Builder's messaging
    # services that formats the key with `dyad_key_for()` above, catches
    # `IntegrityError` and re-fetches.** The constraint is what makes the race safe;
    # the helper is what makes the constraint apply.
    #
    # Re-messaging after an unblock finds the existing hidden conversation through
    # that helper rather than creating a second one, so history reappears in place
    # (ADR-0002). That falls out of the design; it needs no special handling.
    #
    # One honest footnote, because the ACC-4 habit is to notice duplicate indexes:
    # Postgres ends up with a **second** index on this column whether we want it or
    # not. Django adds a `varchar_pattern_ops` `_like` index for any unique or
    # indexed text column, and `dyad_key` is only ever matched for equality, so that
    # one is dead weight. Left alone: it is the same everywhere in the schema
    # (`User.username`, `Post.slug`), this table takes one insert per pair of people
    # ever, and removing it would mean replacing `unique=True` with a
    # `Meta.constraints` `UniqueConstraint` and deviating from §4.1's field spec for
    # a write cost that does not exist. Recorded rather than fixed.
    dyad_key = models.CharField(
        _("dyad key"),
        max_length=DYAD_KEY_MAX_LENGTH,
        unique=True,
        null=True,
        blank=True,
    )

    # ── Why this conversation exists (GAP 11, M5) ────────────────────────────
    #
    # **Jeni's ruling, 4 Oct 2026: add it. Recorded as ADR-0005**, which carries the
    # full trade-off and the two rejected options. Nullable because a
    # profile-initiated DM has no origin post; `SET_NULL` so deleting the idea does
    # not destroy the conversation.
    #
    # M5's conflict, and how the ruling resolves it. `dyad_key` is unique per pair, so
    # there is **one conversation per pair of people, forever** — message someone about
    # idea A, then about idea B three weeks later, and it is the same thread with
    # `origin_post` still pointing at A. The field is therefore **"what this
    # conversation started about", not "what it is about"**, which is option (a) in
    # M5's table: set once at creation, never updated. Option (b),
    # `Message.about_post`, is the natural Phase 2 upgrade and a one-line nullable FK
    # when it is wanted — the same reasoning §2.6 uses for `Comment.parent`. Option
    # (c), dropping `dyad_key` uniqueness so each post gets its own thread, is
    # rejected: it recreates the duplicate-thread race and fragments one person's
    # inbox across ideas.
    #
    # **Two things the context strip must do, because the column cannot** (M5): the
    # copy reads **"Started about: …"** and not "About: …", which is what makes the
    # field truthful in the second-idea case; and because posts are **soft**-deleted
    # (§8), `SET_NULL` will in practice almost never fire, so the strip has to check
    # `origin_post.deleted_at` itself and render "this idea was removed". Without that,
    # the first soft-deleted post gives every reader of that thread a header linking
    # to a 404. Reaching a soft-deleted post through this FK is safe — Django uses
    # `_base_manager` for forward-FK access, so the `ActiveManager` split does not
    # raise — which is precisely why the check has to be explicit rather than arriving
    # as an exception.
    origin_post = models.ForeignKey(
        Post,
        on_delete=models.SET_NULL,
        related_name="conversations_started",
        null=True,
        blank=True,
    )

    # ── Denormalised for the conversation list ───────────────────────────────
    #
    # Both exist so the list renders with **zero joins to `Message`** (§4.1). The
    # index is kept: the list sorts every one of a user's conversations by this
    # column, and no composite on this table leads with it.
    last_message_at = models.DateTimeField(
        _("last message at"), null=True, blank=True, db_index=True
    )
    # Truncated by the send path. `blank=True` and never `null=True`, per §0's text
    # convention — an empty preview is `""`, not NULL, so templates never branch.
    last_message_preview = models.CharField(
        _("last message preview"), max_length=PREVIEW_LENGTH, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        verbose_name = _("conversation")
        verbose_name_plural = _("conversations")
        # No `Meta.ordering` (ACC-14) — a default ordering leaks into joins,
        # subqueries and aggregates, not only the queries that want it. The
        # conversation list sorts explicitly on `-last_message_at`.

    def __str__(self):
        return f"Conversation<{self.pk}> {self.dyad_key or 'group'}"


class ConversationParticipant(models.Model):
    """One person's membership of, and read state over, one conversation.

    **A participant model rather than `user_a` / `user_b` columns** (§4.2): read state
    is per-user and belongs on a per-user row. `user_a` / `user_b` forces
    `Q(a=me) | Q(b=me)` on every query, cannot index cleanly, and has nowhere to put
    `unread_count`, `is_archived` or `last_read_at`.
    """

    # `db_index=False`: `uniq_participant_per_conversation` below leads with
    # `conversation`, so the index Django would build for this FK is a strict prefix of
    # one we already build. Same reasoning as ACC-4. The unique index also serves the
    # CASCADE from `Conversation`.
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
        db_index=False,
    )
    # `db_index=False` for the same reason — `participant_user_idx` leads with `user`.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_participations",
        db_index=False,
    )

    # ── Read state ───────────────────────────────────────────────────────────
    #
    # **M13, and every unread query has to be written this way.** `last_read_at` is
    # nullable, and `last_message_at > NULL` evaluates to NULL in SQL, which filters
    # **out** — so a conversation the user has **never opened** reads as **already
    # read**, exactly backwards, and it lands on the first DM from a stranger, which is
    # the core loop in spec §3.4. Any comparison against this column is:
    #
    #     Q(last_read_at__isnull=True) | Q(last_message_at__gt=F("last_read_at"))
    #
    # **M14:** sending bumps `Conversation.last_message_at`, so the sender's own
    # `last_read_at` must be set in the same transaction as the insert, or their own
    # conversation shows as unread to them the instant they send.
    last_read_at = models.DateTimeField(_("last read at"), null=True, blank=True)

    # ── Decision E — a number, not a dot (Jeni, 4 Oct 2026) ──────────────────
    #
    # M6 asked the question and M2 costed both answers; Jeni chose the number, and
    # `components/_tab_bar.html` renders it. A dot would have been free
    # (`last_message_at > last_read_at`, no column); a live number is a `COUNT(*)`
    # over `Message` per conversation on a badge that renders on **every page load**,
    # which is precisely the aggregate §7 denormalises everything else to avoid. So it
    # is a denormalised counter and it obeys §7 in full: written with `F()` (rule 1),
    # in the same `transaction.atomic()` as the `Message` insert (rule 2),
    # `PositiveIntegerField` with any decrement guarded by `Greatest(F(...) - 1, 0)`
    # (rule 3 — on a `PositiveIntegerField` an unguarded decrement at zero is an
    # `IntegrityError` and a 500 on the screen, not a cosmetic slip), and covered by
    # the weekly reconciliation job (rule 4).
    #
    # Zeroed — not decremented — when the user opens the thread, in the same write
    # that sets `last_read_at`.
    unread_count = models.PositiveIntegerField(_("unread count"), default=0)

    is_archived = models.BooleanField(_("archived"), default=False)
    # **M8 is still open with Jeni and this column has no defined behaviour.** Nothing
    # in the spec, the roadmap or §5 says what muting does; the only plausible meaning
    # is "suppress the `new_message` notification for this conversation", which is a
    # line §5.2 does not have. The column is in the approved §4.2, so it ships —
    # dropping a field the approved contract lists is as much a product decision as
    # adding one. **Do not write to it until the rule exists.** Related and also open:
    # M9 — does a new message un-archive a thread? (Instagram: yes. If it does not,
    # archive silently becomes mute, and M8 gets harder to answer rather than easier.)
    is_muted = models.BooleanField(_("muted"), default=False)

    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("conversation participant")
        verbose_name_plural = _("conversation participants")
        constraints = [
            # One row per person per conversation. Also the index that serves "is this
            # user in this conversation?", which §4.3's rule 1 makes the gate on every
            # single message read.
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="uniq_participant_per_conversation",
            ),
        ]
        indexes = [
            # "My conversations", archived or not (§4.2).
            #
            # An honest caveat, recorded so nobody re-derives it (the Messaging
            # review's closing note): this is **not** a single index-ordered scan. It
            # filters participant rows, then the query sorts on
            # `conversation.last_message_at` — a column on the **joined** table — so
            # Postgres filters, joins and then sorts. At v1 scale (tens to hundreds of
            # conversations per user) that sort is free. Mirroring `last_message_at`
            # onto this row would remove it at the cost of a fourth denormalised copy,
            # and that is the same call §2.3.2 already made for Discovery: do not
            # denormalise until a real `EXPLAIN` says to.
            models.Index(fields=["user", "is_archived"], name="participant_user_idx"),
            # The inbox badge, which renders on **every authenticated page load** —
            # the same justification and the same shape as the notification bell's
            # partial index in §5.1 (M2). Partial on the predicate the badge actually
            # uses, so it indexes only the handful of conversations with something
            # unread in them instead of the user's whole history.
            #
            # **M17:** the badge query must also be block-filtered. Counting these rows
            # directly reports "1 unread" pointing at a conversation `visible_to()` has
            # removed from the list — visible, and confusing in exactly the situation
            # where the user most wants to trust the product. ADR-0003 §4's safety net
            # enumerates authenticated **list URLs**, and the badge is not one, so that
            # test passes while the badge leaks. Same shape and same gap as the bell.
            models.Index(
                fields=["user"],
                condition=Q(unread_count__gt=0),
                name="participant_unread_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.conversation_id}"


class MessageQuerySet(models.QuerySet):
    """**Deliberately not a `BlockAwareQuerySetMixin`** (M15, ADR-0003).

    `Message` has a `sender`, so the generic mixin would apply to it cleanly — and
    applying it is wrong. In a 1:1 thread the **conversation** is already hidden by
    `Conversation.visible_to()`, so per-message filtering is redundant, and the only
    thing it can produce is a half-rendered thread with holes in it. This is an
    explicit "do not", because adding it for symmetry looks like tidiness.

    The absence is checkable: `Message.objects` has no `visible_to` attribute at all,
    the same way `Report.objects` does not (§12.5).
    """

    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveMessageManager(models.Manager.from_queryset(MessageQuerySet)):
    """Default manager — hides soft-deleted messages (§8.2).

    Declared **first** on the model, which matters more than it looks (TS-12): Django
    builds reverse related managers from the model's `_default_manager` class, so if
    `all_objects` came first, `conversation.messages.all()` would start returning
    soft-deleted messages in the thread. Moderation's need to see them is solved in
    the admin by using `all_objects` explicitly, not by reordering these two.
    """

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Message(models.Model):
    """One message in a thread.

    **Two rules for whoever reads this table, both non-negotiable (§4.3):**

    1. Every read goes through
       `Message.objects.filter(conversation__participants__user=request.user)`.
       **Never trust a conversation id from the URL.**
    2. **Blocking never deletes a message.** Hiding is a filter, so unblocking
       restores the thread for free. There must be no code path anywhere that deletes
       a `Message` or a `Conversation` on block — ADR-0002.
    """

    # The FK index is **kept**, unlike `ConversationParticipant`'s two. The thread
    # index below leads with `conversation` but is **partial**, so it does not cover
    # soft-deleted rows — it cannot stand in for the FK's own full index, which is
    # what the CASCADE from `Conversation` and moderation's `all_objects` reads walk.
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    # Index kept: anonymisation (ADR-0001) and account deletion both sweep by sender,
    # and no composite on this table leads with it. `CASCADE` essentially never fires
    # — a `User` row is anonymised, not hard-deleted, which is what keeps a two-person
    # thread from becoming a monologue when one person leaves (§8.1).
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="messages_sent",
    )
    # `MAX_MESSAGE_LENGTH` is form-level only (§0).
    body = models.TextField(_("body"))

    # `db_index=True` exactly as §4.3 specifies. The thread index below leads with
    # `conversation` and is partial, so it is not a substitute for this one.
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # **No `updated_at`.** Messages are not editable — the same call §2.6 makes for
    # `Comment` (deletable, not editable), and there is no DM edit story anywhere in
    # the spec. Adding `auto_now` later is a one-line migration if that changes.
    #
    # Soft delete: a deleted message may still be the evidence attached to an open
    # report (§8), which is the same reason `Post` and `Comment` carry it. No index on
    # the column — the partial thread index already scopes to the live rows, and that
    # is the only query filtering on it. Matches `Comment.deleted_at`.
    #
    # **M7 is still open with Jeni: is this a user-facing delete, or retention only?**
    # The schema is identical either way, which is why it is not blocking. The
    # difference is all Builder-side — a user-facing delete needs an affordance, a
    # "[message deleted]" tombstone in the thread, and the M16 preview recompute. This
    # file assumes **retention-only** until ruled otherwise, matching `Message` having
    # no `updated_at` and comments being deletable-not-editable with no DM equivalent.
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveMessageManager()
    all_objects = models.Manager.from_queryset(MessageQuerySet)()

    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")
        # No `Meta.ordering` (ACC-14). The thread orders explicitly.
        indexes = [
            # The thread, paginated. §4.3 drafted this as
            # `Index(conversation, -created_at)`; M3 corrected it on two counts, both
            # cheap and both already settled practice elsewhere in the schema:
            #
            # 1. **Partial.** Messages are soft-deleted, and `Comment`'s equivalent is
            #    `Index(post, created_at)` partial `WHERE deleted_at IS NULL` (§2.6).
            #    Same query shape, same treatment.
            # 2. **`-id` tie-break.** `created_at` ties are not hypothetical: QA's seed
            #    inserts message runs inside one transaction, and a realistic demo
            #    thread is exactly where they cluster. Ties make keyset pagination skip
            #    and repeat rows, and produce ordering tests that fail one run in
            #    twenty. This is the same fix PF-1 applied to both feed indexes
            #    (§12.2), for the same reason.
            models.Index(
                fields=["conversation", "-created_at", "-id"],
                condition=Q(deleted_at__isnull=True),
                name="message_thread_idx",
            ),
        ]

    def __str__(self):
        return f"Message<{self.pk}> from {self.sender_id}"
