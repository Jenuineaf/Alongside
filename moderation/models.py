"""Trust & Safety models — the report, and the queue that works it.

Owned by the Architect (`CLAUDE.md` rule 2). The **Builder seat** owns the report
form, the "Report" buttons, the rate limiting and the stale-post job, and reads and
writes this table; it does not edit this file. Schema changes go seat → Jeni →
Architect → `docs/data-model.md` → migration.

Contents follow `data-model.md` §6.1, as amended by the Trust & Safety seat's review
(`docs/review/trust-safety.md`, TS-4 and TS-12) and QA finding 6
(`docs/review/qa.md`). Where a review or a ruling changed something, the finding id
is cited inline so the reasoning is one grep away.

**Two of Jeni's open decisions (§12.4) closed on 3 Oct 2026, and both land here.**

*Decision H — sign-in is required to report* (§12.4, TS-9). `CLAUDE.md` rule 7 names
post / follow / spark / comment / DM as the gated actions and is silent on reporting,
so this was Jeni's to rule and she has: **report requires an account.** It is what
gives the three anti-brigading constraints below something to key on — with anonymous
reports, NULL reporters never collide in a unique index, so all three would stop
working at once, and the rate limiter would fall back to an IP address that behind
Render's proxy may be one shared key for every visitor. The nullability of `reporter`
is a *separate* question with a *separate* answer; see the field itself.

*Decision I — yes, a `demo_moderator` Group*, created in `moderation` 0002 as a data
migration. QA finding 6: `testing.md` §7.5 publishes a staff account's credentials on
the login screen so the moderation queue is demoable in a portfolio piece, and
`is_public_demo` is an application-layer permission check that **Django admin never
consults**. Without the Group, anyone reading the login screen can open `/admin/` and
empty the database.

**There is deliberately no `visible_to()` in this app, and it is the one place in the
project where that is correct.** Every other model carries `BlockAwareQuerySetMixin`
— see `PostQuerySet`, `CommentQuerySet`, `ProfileQuerySet`, `NotificationQuerySet`.
Moderation queries **deliberately bypass the block filter** (ADR-0003, §1.6, §6.1): a
moderator reviewing a report has very often been blocked by the person they are
reviewing — that is what being reported for harassment tends to involve — and a
block-filtered queue would hide exactly the rows it exists to show. The soft-delete
managers are bypassed for the same reason, in the admin classes rather than here
(TS-12). So: `Report` has one plain manager, no `QuerySet` mixin, and no
`all_objects`. **This is not an oversight. A block filter here blinds the queue.**

`Report` is also the one content-bearing model with **no `deleted_at`** — it carries
no soft delete because it *is* the evidence that justifies everyone else's (§8).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from posts.models import Comment, Post

# Form-level caps, same convention as `posts.models` and for the same reason: §0 says
# `TextField(N)` is enforced in forms only and never in Postgres, and these live on
# the model so the form, the DRF serializer, the tests and the seed all read one
# number. A test that posts 5000 characters through the ORM will succeed, by design.
MAX_DETAILS_LENGTH = 1000
MAX_RESOLUTION_NOTE_LENGTH = 500

# The Group from Decision I, created in `moderation` 0002. Named here so the data
# migration, the seed command (`demo.mod@` goes in it) and QA's "no delete_* on any
# installed model" assertion all spell it the same way.
DEMO_MODERATOR_GROUP = "demo_moderator"


class ReportReason(models.TextChoices):
    """Why it was reported. §6.1's list, unchanged.

    `OTHER` is the escape hatch, and the Builder's form requires `details` when it is
    chosen — a bare "other" with no text is an unactionable row in the queue.
    """

    SPAM = "spam", _("Spam")
    HARASSMENT = "harassment", _("Harassment or abuse")
    SCAM = "scam", _("Scam or fraud")
    INAPPROPRIATE = "inappropriate", _("Inappropriate content")
    IMPERSONATION = "impersonation", _("Impersonation")
    OTHER = "other", _("Something else")


class ReportStatus(models.TextChoices):
    OPEN = "open", _("Open")
    REVIEWING = "reviewing", _("Reviewing")
    ACTIONED = "actioned", _("Actioned")
    DISMISSED = "dismissed", _("Dismissed")


# The two statuses that mean "this report is still live". Used by the three
# conditional unique constraints below and by the admin's queue actions. A single
# name, because the day someone adds a fifth status they have to decide which side of
# this line it falls on, and having to edit one tuple is the prompt to do so.
UNRESOLVED_STATUSES = (ReportStatus.OPEN, ReportStatus.REVIEWING)


class Report(models.Model):
    """One report of one target, and the moderator's disposition of it.

    Three nullable target FKs plus a check constraint, exactly as `Notification`
    (§5.1) does it, rather than a `GenericForeignKey`: the target types are three,
    known and closed, so concrete FKs give real referential integrity, a
    `UniqueConstraint` that actually works, and `select_related()` on the changelist.

    **No `ModerationAction` model in v1** (§6.1), and the Trust & Safety review agrees
    (`trust-safety.md` §3): `status` + `resolution_note` + `reviewed_by` is enough for
    a Django-admin queue, and Django already writes a full audit row per change
    (`django.contrib.admin.models.LogEntry`: who, when, which object, what changed).
    That audit trail is free **on the condition that every moderation action goes
    through the admin UI and not `manage.py shell`.**
    """

    # ── Who reported ─────────────────────────────────────────────────────────
    #
    # `SET_NULL, null=True`, and **`CASCADE` and `null=False` are both wrong.** The
    # two reasons people reach for them are different, and so are the answers:
    #
    # 1. "Reports can be anonymous, so the reporter is optional." **No** — Decision H
    #    (Jeni, 3 Oct 2026): sign-in is REQUIRED to report. The Builder's view is
    #    login-gated, so in practice this column is never written NULL.
    # 2. "Then make it `null=False`." **Also no** — a report must survive the reporter
    #    deleting their account (§6.1). A report must not be neutralisable by its
    #    author walking away, which is the same reasoning ADR-0001 uses to keep posts
    #    and comments. `CASCADE` would delete the evidence; `null=False` would block
    #    the deletion path outright.
    #
    # So: required at the application layer, nullable at the database layer, and the
    # two are not in tension. Under ADR-0001 a `User` row is never hard-deleted
    # (deletion anonymises), so `SET_NULL` will in practice almost never fire — it is
    # the correct floor, not the expected path.
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reports_filed",
        null=True,
        blank=True,
    )

    # ── The target: exactly one of these three ───────────────────────────────
    #
    # All three CASCADE, and **none of them ever fires through the product**: accounts
    # anonymise (ADR-0001) and posts and comments soft-delete (§8), so the row a
    # report points at is still there. The one exposed path is Django admin's own hard
    # delete, which would cascade away the record of the thing the moderator just
    # actioned — TS-13. That is closed in `moderation/admin.py` by refusing delete
    # permission on `Post` and `Comment`, not here: `SET_NULL` on these columns would
    # break `report_exactly_one_target` below, which is load-bearing.
    #
    # The FK indexes are kept (unlike `status`): "every report against this post" and
    # "has this account been reported before" are both queue queries, and neither
    # composite index leads with these columns.
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_against",
        null=True,
        blank=True,
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="reports",
        null=True,
        blank=True,
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="reports",
        null=True,
        blank=True,
    )

    # ── What they said ───────────────────────────────────────────────────────
    reason = models.CharField(_("reason"), max_length=20, choices=ReportReason.choices)
    # `MAX_DETAILS_LENGTH` is form-level only (§0). The form requires this field when
    # `reason="other"`.
    details = models.TextField(_("details"), blank=True)

    # ── What we did about it ─────────────────────────────────────────────────
    #
    # No `db_index=True` on `status`, even though §6.1 says "indexed": the
    # `report_queue_idx` composite below leads with `status`, so the index Django
    # would build for this column is a strict prefix of one we already build. Same
    # reasoning as ACC-4, which dropped four indexes for duplicating an FK's own, and
    # as `Notification.recipient`. The queue's real query — `WHERE status='open'
    # ORDER BY created_at` — is served by the composite: an equality filter on its
    # leading column lets Postgres walk the second column in either direction.
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=ReportStatus.choices,
        default=ReportStatus.OPEN,
    )
    # `MAX_RESOLUTION_NOTE_LENGTH` is form-level only (§0). This, plus `status` and
    # `reviewed_by`, is what stands in for a `ModerationAction` row.
    resolution_note = models.TextField(_("resolution note"), blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reports_reviewed",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)

    # `db_index=True` is not covered by `report_queue_idx`, which leads with `status`:
    # the unfiltered changelist orders every report by age regardless of status.
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("report")
        verbose_name_plural = _("reports")
        # No `Meta.ordering` (ACC-14) — a default ordering leaks into joins,
        # subqueries and aggregates, not only the queries that want it. The admin
        # sets its own, which is the only place that needs one.
        constraints = [
            # Exactly one target. An explicit three-way OR because Django has no
            # count-style shortcut, and `condition=` rather than the deprecated
            # `check=` because this is Django 5.2 (renamed in 5.1, gone in 6.0).
            #
            # Without it, a report with all three targets null is legal and sits in
            # the queue pointing at nothing, and a report with two is legal and makes
            # `target` below ambiguous — both unactionable rows that read as bugs in
            # the queue rather than as bad writes.
            models.CheckConstraint(
                condition=(
                    Q(reported_user__isnull=False, post__isnull=True, comment__isnull=True)
                    | Q(reported_user__isnull=True, post__isnull=False, comment__isnull=True)
                    | Q(reported_user__isnull=True, post__isnull=True, comment__isnull=False)
                ),
                name="report_exactly_one_target",
            ),
            # ── Anti-brigading: one UNRESOLVED report per person per target ──
            #
            # **The condition is the whole point.** Written without it, each of these
            # means "one report EVER": someone reports a post, a moderator dismisses
            # it, the post gets worse, and that person can never report it again —
            # §9.1 finding 2, which is why the condition is in the approved document
            # rather than being an optimisation. It compiles to a Postgres partial
            # unique index, so it costs almost nothing and scopes itself to live rows.
            #
            # `*__isnull=False` is TS-4, and it closes a trap rather than changing
            # behaviour. Postgres treats NULLs as distinct in a unique index, which is
            # *why* three separate constraints can coexist: on a user-report
            # `post IS NULL`, so `(reporter, post)` never collides. Nobody had written
            # that down, and Django 5.1+ ships `UniqueConstraint(nulls_distinct=False)`
            # — the day someone sets that flag, reasonably believing they are
            # tightening things, **every user-report in the system collides on
            # `(reporter, NULL)` and only one person can ever report anyone.** With
            # the predicate explicit, each index is scoped by intent instead of by an
            # accident of NULL semantics, and that flag becomes harmless.
            #
            # These stop duplicate reports of the SAME target only. One account can
            # still flood the queue with fifty different targets; that is the rate
            # limiter's job (`django-ratelimit` against Redis, no table), and Decision
            # H is what lets it key on `user` instead of a proxy-shared IP.
            #
            # Names kept verbatim from `trust-safety.md` TS-4 so the review and the
            # schema match on a grep.
            models.UniqueConstraint(
                fields=["reporter", "post"],
                condition=Q(status__in=UNRESOLVED_STATUSES, post__isnull=False),
                name="uniq_open_report_per_post",
            ),
            models.UniqueConstraint(
                fields=["reporter", "comment"],
                condition=Q(status__in=UNRESOLVED_STATUSES, comment__isnull=False),
                name="uniq_open_report_per_comment",
            ),
            models.UniqueConstraint(
                fields=["reporter", "reported_user"],
                condition=Q(status__in=UNRESOLVED_STATUSES, reported_user__isnull=False),
                name="uniq_open_report_per_user",
            ),
        ]
        indexes = [
            # The admin queue (§6.1), shape exactly as the approved document
            # specifies. Oldest-open-first is `WHERE status='open' ORDER BY
            # created_at`: the equality filter pins the leading column, so Postgres
            # satisfies ascending `created_at` with a backward scan of this index.
            models.Index(fields=["status", "-created_at"], name="report_queue_idx"),
        ]

    def __str__(self):
        return f"Report<{self.pk}> {self.reason} ({self.status})"

    # Not a column — a one-line read over the three FKs, so the queue and the
    # Builder's "you already reported this" check do not each reimplement the
    # precedence. `report_exactly_one_target` guarantees exactly one is set, so the
    # `or` chain is total and unambiguous. Reaching a soft-deleted `post` or
    # `comment` through it is safe: Django uses `_base_manager` for forward-FK
    # descriptor access, so the `ActiveManager` split (§8.2) does not raise here.
    @property
    def target(self):
        return self.reported_user or self.post or self.comment
