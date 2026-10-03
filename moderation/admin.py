"""The moderation queue. It is Django admin, and that is the design.

§6.1: **no custom moderation UI in v1** — `status` + `resolution_note` +
`reviewed_by` on the report is enough, and `django.contrib.admin.models.LogEntry`
gives a full audit row per change (who, when, which object, what changed) for free.
That audit trail is free **on the condition that every moderation action goes through
this UI and not `manage.py shell`** (`trust-safety.md` §3), which is why the queue
actions below write `LogEntry` rows by hand rather than taking the cheap bulk
`UPDATE`.

This module is admin registration only: no views, no URLs, no templates. The Builder
seat owns the report *form*, the "Report" buttons and the rate limiting.

**Three things here exist to stop the queue being blind or dangerous:**

1. **`get_queryset()` uses `all_objects`** on `Post` and `Comment` (ADR-0003, §6.1,
   TS-12). Those models declare `objects = Active*Manager()` **first**, deliberately:
   Django builds reverse related managers from `_default_manager`, so reordering them
   would make `post.comments.all()` return soft-deleted comments on the public post
   page. The fix therefore belongs here, per-admin, and not in the model — and
   without it a moderator reviewing a report about a deleted post sees an empty
   changelist, which is exactly the blindness §6.1 warns about.
2. **No block filtering anywhere in this app.** `visible_to()` is deliberately not
   called (§1.6) — a moderator reviewing a harassment report has usually been blocked
   by the person they are reviewing.
3. **Hard delete is refused on `Post` and `Comment`** (TS-13). `Report.post` and
   `Report.comment` are `CASCADE`, which never fires through the product because both
   models soft-delete — but admin offers a hard delete by default, so actioning a
   report by deleting the post would cascade away the record of the action. Takedown
   goes through the soft-delete services, which also move the counters §7.1 requires.

**`Post` and `Comment` are registered here and nowhere else.** They are registered in
`moderation` rather than in `posts` because admin is purely a moderation surface in
this product (`product-spec.md` §4.7) — there is no author-facing admin. A later
`posts/admin.py` registering either model will raise `AlreadyRegistered`; extend
these classes instead, or move them and keep the `get_queryset` override.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from moderation.models import Report, ReportStatus
from posts.models import Comment, Post


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """The queue. Open the Status filter on `open` and work it oldest-first."""

    # `created_at` ascending: oldest first, which is the queue order §6.1 asks for.
    # Combined with the Status filter it is also the query `report_queue_idx` is
    # shaped for — an equality filter on the leading column lets Postgres satisfy
    # ascending `created_at` with a backward scan.
    ordering = ("created_at",)
    date_hierarchy = "created_at"

    list_display = (
        "created_at",
        "status",
        "reason",
        "target_summary",
        "reporter",
        "reviewed_by",
        "reviewed_at",
    )
    list_display_links = ("created_at", "status")
    # `status` first: it is the filter that turns this changelist into a queue.
    list_filter = ("status", "reason", "created_at")
    search_fields = (
        "details",
        "resolution_note",
        "reporter__username",
        "reported_user__username",
        "post__title",
        "comment__body",
    )

    # The only two editable fields, which is the whole of the job (§6.1). Everything
    # else is a fact about the report: who filed it, against what, and why. A
    # moderator who could edit `reason` or `details` could rewrite the complaint they
    # are ruling on, and `LogEntry` would faithfully record them doing it.
    fields = ("target_preview", "report_facts", "status", "resolution_note")
    readonly_fields = ("target_preview", "report_facts")

    actions = ("mark_reviewing", "mark_actioned", "mark_dismissed")

    def save_model(self, request, obj, form, change):
        # The change form edits `status` but cannot edit `reviewed_by` / `reviewed_at`
        # — they are not in `fields`, deliberately: a moderator should not be able to
        # attribute their own decision to somebody else. So the stamp happens here,
        # for the same reason the actions do it: a report that says "actioned" without
        # saying who decided that is not an audit trail.
        if "status" in form.changed_data and obj.status != ReportStatus.OPEN:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        # `select_related` on all five FKs: the changelist renders the reporter, the
        # reviewer and the target on every row, and `target_summary` dereferences
        # whichever target is set. Without this the queue is a 5N+1.
        #
        # No `all_objects` needed on `Report` itself — reports are not soft-deleted
        # (§8); the report *is* the evidence that justifies everyone else's delete.
        # The soft-deleted `post` / `comment` it points at still arrive, because a
        # `select_related` JOIN from this queryset does not consult the related
        # model's manager, and forward-FK descriptor access uses `_base_manager`.
        return (
            super()
            .get_queryset(request)
            .select_related("reporter", "reported_user", "post", "comment", "reviewed_by")
        )

    def has_add_permission(self, request):
        # Reports come from the report form. A hand-made report has no real reporter
        # and would sit in the queue misrepresenting where it came from.
        return False

    # ── Read-only renderings of the thing being reported ─────────────────────

    @admin.display(description=_("target"))
    def target_summary(self, obj):
        """One cell naming the target, for `list_display`.

        `Report` has three nullable target FKs and a check constraint rather than a
        `GenericForeignKey` (§6.1), so the changelist needs a computed column —
        flagged by the Trust & Safety review as admin code, not a schema problem.
        """
        target = obj.target
        if target is None:
            return "—"
        if obj.post_id:
            return f"post: {Truncator(obj.post.title).chars(50)}"
        if obj.comment_id:
            return f"comment: {Truncator(obj.comment.body).chars(50)}"
        return f"user: {target.username}"

    @admin.display(description=_("reported content"))
    def target_preview(self, obj):
        """The reported content, inline and read-only.

        This is what lets `demo_moderator` hold `view_report` + `change_report` and
        **nothing else** (Decision I) while still being able to do the job: the
        content is rendered here, so working the queue needs no permission on `Post`,
        `Comment` or `User`.

        Two warnings are rendered because both change how a report should be read:

        - **soft-deleted** — the content is already gone from the site, so a takedown
          is not the action needed.
        - **edited after this report was filed** — the partial answer to TS-3. Posts
          are editable, so someone can post something abusive, get reported, and edit
          it innocuous before review; a moderator comparing timestamps at least knows
          the text on screen is not necessarily the text that was reported. It is
          **not** a substitute for TS-3's `target_snapshot`, which is still open with
          Jeni and cannot be back-filled.
        """
        target = obj.target
        if target is None:
            return "—"

        if obj.post_id:
            heading = f"Post: {obj.post.title}"
            body = Truncator(obj.post.body).chars(2000)
            author = obj.post.author
        elif obj.comment_id:
            heading = f"Comment on: {obj.comment.post.title}"
            body = Truncator(obj.comment.body).chars(2000)
            author = obj.comment.author
        else:
            heading = f"User: {target.username}"
            body = target.display_name or ""
            author = target

        warnings = []
        if getattr(target, "deleted_at", None):
            warnings.append(_("Already soft-deleted — no longer visible on the site."))
        updated_at = getattr(target, "updated_at", None)
        if updated_at and obj.created_at and updated_at > obj.created_at:
            warnings.append(_("Edited after this report was filed — see TS-3."))

        return format_html(
            "<p><strong>{}</strong><br>by {}</p><pre "
            'style="white-space:pre-wrap;max-width:60em">{}</pre>{}',
            heading,
            getattr(author, "username", "—"),
            body,
            format_html_join("", "<p><strong>! {}</strong></p>", ((w,) for w in warnings)),
        )

    @admin.display(description=_("report"))
    def report_facts(self, obj):
        """Who filed it, why, and what they wrote — as text, not editable fields."""
        reporter = obj.reporter.username if obj.reporter_id else _("[deleted account]")
        return format_html(
            "<p>{} &middot; <strong>{}</strong> &middot; filed {}</p>"
            '<pre style="white-space:pre-wrap;max-width:60em">{}</pre>',
            reporter,
            obj.get_reason_display(),
            obj.created_at,
            obj.details or "—",
        )

    # ── Queue actions ────────────────────────────────────────────────────────
    #
    # All three set `reviewed_by` and `reviewed_at` alongside `status`, because a
    # report that says "actioned" without saying who decided that is not an audit
    # trail. `reviewing` sets them too: it means "I have picked this up", and the
    # point of the status is to tell the other moderator who has it.
    #
    # They loop and call `log_change()` rather than taking one bulk `UPDATE`.
    # `QuerySet.update()` writes no `LogEntry`, and `LogEntry` is the entire reason
    # §6.1 can say "no `ModerationAction` model in v1" — a bulk update would quietly
    # drop the audit trail that decision rests on. At queue scale (tens of rows) the
    # loop costs nothing.
    #
    # Moving a report out of `open`/`reviewing` also releases the partial unique
    # index (`uniq_open_report_per_*`), which is exactly §9.1 finding 2: after a
    # dismissal the same person can report the same target again.

    def _set_status(self, request, queryset, status, message):
        now = timezone.now()
        count = 0
        for report in queryset:
            report.status = status
            report.reviewed_by = request.user
            report.reviewed_at = now
            report.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            self.log_change(request, report, message)
            count += 1
        self.message_user(request, f"{count} report(s): {message}.")

    @admin.action(description=_("Mark as reviewing (I have picked this up)"))
    def mark_reviewing(self, request, queryset):
        self._set_status(request, queryset, ReportStatus.REVIEWING, "Marked reviewing")

    @admin.action(description=_("Mark as actioned (add a resolution note too)"))
    def mark_actioned(self, request, queryset):
        self._set_status(request, queryset, ReportStatus.ACTIONED, "Marked actioned")

    @admin.action(description=_("Dismiss (add a resolution note too)"))
    def mark_dismissed(self, request, queryset):
        self._set_status(request, queryset, ReportStatus.DISMISSED, "Dismissed")


class SoftDeleteModerationAdmin(admin.ModelAdmin):
    """Shared base for the two soft-deleted models the queue has to look at.

    `all_objects` is the point: see TS-12 and this module's docstring.
    """

    def get_queryset(self, request):
        # NOT `super().get_queryset(request)` — that goes through `_default_manager`,
        # which is `ActivePostManager` / `ActiveCommentManager` and filters out
        # exactly the rows a moderator needs. Ordering is applied here because
        # bypassing `super()` bypasses its `get_ordering()` handling too.
        queryset = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        return queryset.order_by(*ordering) if ordering else queryset

    def has_delete_permission(self, request, obj=None):
        # TS-13. Admin's hard delete would cascade away the `Report` that justified
        # the takedown. Use the soft-delete action instead, which also moves the
        # counters §7.1 requires.
        return False

    @admin.display(boolean=True, description=_("live"))
    def is_live(self, obj):
        return obj.deleted_at is None


@admin.register(Post)
class PostModerationAdmin(SoftDeleteModerationAdmin):
    ordering = ("-published_at",)
    date_hierarchy = "published_at"
    list_display = ("title", "author", "status", "is_stale", "is_live", "published_at")
    list_filter = ("status", "stage", "commitment", "is_stale")
    search_fields = ("title", "body", "author__username")
    # `deleted_at` is read-only on purpose: writing it by hand here skips
    # `soft_delete_post()` and leaves `Profile.post_count`, `Tag.post_count` and
    # `Role.usage_count` one too high, with the notifications still pointing at a
    # post nobody can see (§7.1, S8). Use the action.
    readonly_fields = ("deleted_at", "created_at", "updated_at", "last_activity_at")
    actions = ("take_down",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("author")

    @admin.action(description=_("Take down (soft delete, keeps the report)"))
    def take_down(self, request, queryset):
        # Imported here, not at module scope: this is the Builder seat's service and
        # the only correct way to remove a post (§7.1 counters, S8 notifications, all
        # in one transaction). A local import keeps `moderation` from importing
        # `posts.services` at app-load time.
        from posts.services import soft_delete_post

        moved = 0
        for post in queryset:
            if soft_delete_post(post):
                self.log_change(request, post, "Taken down (soft delete)")
                moved += 1
        self.message_user(request, f"{moved} post(s) taken down.")


@admin.register(Comment)
class CommentModerationAdmin(SoftDeleteModerationAdmin):
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_display = ("__str__", "author", "post", "is_live", "created_at")
    search_fields = ("body", "author__username", "post__title")
    # Same reason as `Post.deleted_at`: setting it here leaves `Post.comment_count`
    # one too high, so the post reads "12 comments" above 11 rendered rows.
    readonly_fields = ("deleted_at", "created_at", "updated_at")
    actions = ("take_down",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("author", "post")

    @admin.action(description=_("Take down (soft delete, keeps the report)"))
    def take_down(self, request, queryset):
        from social.services import soft_delete_comment

        moved = 0
        for comment in queryset:
            if soft_delete_comment(comment):
                self.log_change(request, comment, "Taken down (soft delete)")
                moved += 1
        self.message_user(request, f"{moved} comment(s) taken down.")
