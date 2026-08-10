"""Posts & Feed models — the core object of the product.

Owned by the Architect (`CONTRIBUTING.md` rule 2). The Posts & Feed, Discovery, Social
and Trust & Safety seats all read and write these tables; none of them edit this
file. Schema changes go seat → Jeni → Architect → `docs/data-model.md` → migration.

Contents follow `data-model.md` §2, as amended by the eight schema reviews in
`docs/review/`. Where a review changed something, the finding id is cited inline so
the reasoning is one grep away.

`Comment`, `PostSpark`, `CommentSpark` and `SavedPost` also belong to this app
(§2.6–2.8) but land in a later migration with the Social phase, per the roadmap
build order.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.blocking import BlockAwareQuerySetMixin

# Form-level caps. Deliberately not database constraints — `data-model.md` §0 and
# §9 Q8 settled that these belong in the form, and QA has confirmed no test asserts
# a DB limit that isn't there. They live here rather than in the Posts seat's forms
# so that the DRF serializer and the seed command read the same numbers: PF-5 makes
# the point that "enforced in the form" is not sufficient once an API exists.
MAX_TAGS_PER_POST = 5
MAX_CURATED_ROLES_PER_POST = 5
MAX_CUSTOM_ROLES_PER_POST = 3
MAX_IMAGES_PER_POST = 5

# PF-5. Every other freeform field carries a cap; `body` had none. Postgres
# `to_tsvector()` hard-errors above 1MB of input, and with CELERY_TASK_ALWAYS_EAGER
# in production (deployment.md §4) that surfaces as a 500 on the create-post request
# — triggerable by anyone pasting a large document. 20k is far longer than any real
# idea write-up and far under the ceiling.
MAX_BODY_LENGTH = 20_000


class Tag(models.Model):
    """One shared vocabulary for post topics, profile interests and profile fields.

    Same table on purpose (ADR-0004): the Home feed matches a user's interest tags
    and their `field_tag` against post tags, and that only works if they are the
    same rows. There is deliberately **no `kind` column** — partitioning the table
    into sets that must never mix is what made "top posts in your field this week"
    structurally incapable of returning a row.
    """

    name = models.CharField(_("name"), max_length=40)
    slug = models.SlugField(_("slug"), max_length=40, unique=True)
    # Does the display concern `kind` was reaching for, without partitioning
    # anything: only curated tags appear in the onboarding field picker.
    is_curated = models.BooleanField(
        _("curated"),
        default=False,
        help_text=_("Seeded broad tags. Only these appear in the onboarding field picker."),
    )
    post_count = models.PositiveIntegerField(_("post count"), default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("tag")
        verbose_name_plural = _("tags")

    def __str__(self):
        return self.name


class RoleCategory(models.TextChoices):
    ENGINEERING = "engineering", _("Engineering")
    DESIGN = "design", _("Design")
    PRODUCT = "product", _("Product")
    BUSINESS = "business", _("Business")
    CREATIVE = "creative", _("Creative")
    OTHER = "other", _("Other")


class Role(models.Model):
    """What a person does — a different dimension from `Tag`, with the opposite rules.

    A tag describes what an idea is *about*; a role describes what a *person* does.
    Crucially, roles are **exact-match filtered** and tags are not, so role
    vocabulary drift breaks a feature ("Backend Dev" vs "backend engineer" silently
    halves a filtered result set) while tag drift only softens search. That
    asymmetry is why roles are curated and tags are free text (ADR-0004).

    The "Other" escape hatch lives in `Post.custom_roles` / `Profile.custom_skills`:
    searchable, never filterable.
    """

    name = models.CharField(_("name"), max_length=50)
    slug = models.SlugField(_("slug"), max_length=50, unique=True)
    category = models.CharField(
        _("category"),
        max_length=20,
        choices=RoleCategory.choices,
        default=RoleCategory.OTHER,
        help_text=_("Groups the role picker."),
    )
    is_curated = models.BooleanField(_("curated"), default=True)
    # PF-6(a): this counts LIVE POSTS requesting the role. Not profiles claiming
    # it as a skill. Left ambiguous, two seats would increment the same column with
    # different meanings and the reconciliation task could not be written at all.
    usage_count = models.PositiveIntegerField(
        _("usage count"),
        default=0,
        help_text=_("Live posts requesting this role. Profile skills do not touch it."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("role")
        verbose_name_plural = _("roles")
        indexes = [
            # The role picker groups by category; nothing else filters on it.
            models.Index(fields=["category", "name"], name="role_category_name_idx"),
        ]

    def __str__(self):
        return self.name


class Stage(models.TextChoices):
    IDEA = "idea", _("Just an idea")
    BUILDING = "building", _("Already building")
    LAUNCHED = "launched", _("Launched")


class Commitment(models.TextChoices):
    CASUAL = "casual", _("Casual or weekend project")
    SERIOUS = "serious", _("Serious, aiming to build a company")


class PostStatus(models.TextChoices):
    LOOKING = "looking", _("Still looking")
    TEAM_FORMED = "team_formed", _("Team formed")
    CLOSED = "closed", _("Closed")


# The condition every feed and filter index is partial on, and the condition every
# feed query must therefore match for the index to be used.
#
# It excludes `team_formed` and `closed` because spec §4.8 says those "get posts out
# of the active feed" — that is the author's own choice. It does NOT exclude
# `is_stale`, which is the system's judgement: stale posts are ranked lower, never
# hidden. `is_stale` is the leading SORT column instead (§2.3.2).
_FEED_CONDITION = Q(deleted_at__isnull=True, status=PostStatus.LOOKING)


class PostQuerySet(BlockAwareQuerySetMixin, models.QuerySet):
    block_filter_field = "author"

    def active(self):
        return self.filter(deleted_at__isnull=True)

    def for_viewer(self, user):
        """Annotate `is_sparked` / `is_saved` for this viewer (Designer GAP 3).

        Every feed card renders whether *this* viewer has sparked and saved the
        post. Neither is a column — correctly, they are `PostSpark` / `SavedPost`
        rows — but without one named method the obvious implementation checks per
        card, which is an N+1 on the most-hit query in the app. Six seats cannot see
        each other's chats, so more than one of them would write it that way.

        Anonymous short-circuits to `False` for both without touching the database.

        Chains after `visible_to()`:
            Post.objects.visible_to(request.user).for_viewer(request.user)
        """
        from django.db.models import Exists, OuterRef, Value

        if user is None or not getattr(user, "is_authenticated", False):
            return self.annotate(
                is_sparked=Value(False, output_field=models.BooleanField()),
                is_saved=Value(False, output_field=models.BooleanField()),
            )

        # Imported lazily: these models land with the Social phase, and this method
        # is defined before them.
        from posts.models import PostSpark, SavedPost

        return self.annotate(
            is_sparked=Exists(PostSpark.objects.filter(post_id=OuterRef("pk"), user_id=user.pk)),
            is_saved=Exists(SavedPost.objects.filter(post_id=OuterRef("pk"), user_id=user.pk)),
        )


class ActivePostManager(models.Manager.from_queryset(PostQuerySet)):
    """Default manager — hides soft-deleted rows.

    Declared FIRST on the model, which matters more than it looks (TS-12). Django
    builds reverse related managers from the model's `_default_manager` class, so if
    `all_objects` came first, `post.comments.all()` would start returning
    soft-deleted comments on the public post detail page.

    The moderation queue's need to SEE soft-deleted rows is solved in the admin
    classes by overriding `get_queryset()` to use `all_objects` — not by reordering
    the managers, which would trade a visible problem for an invisible one.
    """

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Post(models.Model):
    """An idea, plus the roles needed to build it.

    Stage, commitment and status are the anti-ghosting design (`CONTRIBUTING.md`), not
    decoration: mismatched expectations are the documented #1 killer in this
    category, so these fields are load-bearing.
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts"
    )
    title = models.CharField(_("title"), max_length=140)
    # slugify(title) + a short random suffix, generated once and never regenerated,
    # so editing a title does not rot every link to the post.
    slug = models.SlugField(_("slug"), max_length=160, unique=True)
    body = models.TextField(_("body"))

    # No db_index on stage/commitment/city_slug individually: the partial composite
    # indexes below lead with each of them, which is what Discovery's filters
    # actually query (D3, and ACC-4's argument against duplicate btrees).
    stage = models.CharField(_("stage"), max_length=12, choices=Stage.choices)
    commitment = models.CharField(_("commitment"), max_length=10, choices=Commitment.choices)

    city = models.CharField(_("city"), max_length=80, blank=True)
    city_slug = models.SlugField(_("city slug"), max_length=80, blank=True, db_index=False)
    is_remote_friendly = models.BooleanField(_("remote friendly"), default=False)

    # Author-controlled. The stale job never writes this.
    status = models.CharField(
        _("status"), max_length=12, choices=PostStatus.choices, default=PostStatus.LOOKING
    )

    # System-controlled, set by the nudge job. Separate from `status` precisely so
    # the job can never overwrite what the author chose. No db_index: a boolean
    # where ~90% of rows are False is not worth an index of its own, and it leads
    # the composites below anyway (D3).
    is_stale = models.BooleanField(_("stale"), default=False)
    nudged_at = models.DateTimeField(_("last nudged"), null=True, blank=True)

    # ── The two writable timestamps ──────────────────────────────────────────
    # ORDER MATTERS HERE. Both default to `timezone.now`, and Django evaluates
    # field defaults in declaration order — so `published_at` must be declared
    # first, or its default lands microseconds AFTER `last_activity_at` and the
    # CheckConstraint below fails on every single insert.
    #
    # `published_at` is separate from `created_at` (which is auto_now_add and
    # therefore immutable) because the seed must write arbitrary dates: a demo feed
    # where all 45 posts say "2 minutes ago" reads as faker than lorem ipsum
    # (testing.md §7.2). It is also the feed's sort key, so editing never reshuffles
    # the feed. There are no drafts in v1 — a post is live when created.
    published_at = models.DateTimeField(_("published"), default=timezone.now, db_index=True)

    # Same trap, one row down (PF-3, TS-1, QA-4). Without a writable default every
    # seeded post would have `last_activity_at = now`, so NOT ONE could ever go
    # stale — and the anti-ghosting feature, which spec §4.8 calls the #1 killer in
    # this category, would be invisible on the deployed demo.
    #
    # Bumped by author edit, new comment, and the author's explicit "yes, still
    # looking". NOT by sparks (TS-6, Q-S1): a spark is a stranger's one click and
    # says nothing about whether the author is still looking, which is the only
    # question the nudge asks. Left in, any passer-by could keep a dead post alive.
    # Always via `touch_activity()` — never written directly.
    last_activity_at = models.DateTimeField(_("last activity"), default=timezone.now)

    # ── Discovery ────────────────────────────────────────────────────────────
    # The "Other" free-text roles. Searchable at weight B, never filterable — that
    # combination is exactly what ADR-0004 option (c) bought.
    custom_roles = ArrayField(
        models.CharField(max_length=50), default=list, blank=True, size=MAX_CUSTOM_ROLES_PER_POST
    )
    keywords = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    # Contents (§2.3, as corrected by PF-4 and D2):
    #   title                                                  A
    #   tags.name + roles_needed.name + custom_roles + keywords B
    #   body                                                   C
    #   city                                                   D
    #
    # The curated role and tag NAMES are in there deliberately. Without them,
    # searching "illustrator" found the post where somebody typed it into the Other
    # box and missed every post that correctly selected the curated Illustrator
    # role — the user who filled the form in properly became the unfindable one.
    #
    # Refreshed by an explicit `refresh_search_vector(post)` call at the end of any
    # transaction that writes post content OR its M2M rows — NOT a `post_save` or
    # `m2m_changed` signal. post_save fires before the M2M rows exist, so the vector
    # would permanently contain no tags and no roles; m2m_changed fires four times
    # per save and recomputes each time.
    search_vector = SearchVectorField(null=True, editable=False)

    # ── Denormalised counters (§7) ───────────────────────────────────────────
    spark_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    save_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    tags = models.ManyToManyField(Tag, through="PostTag", related_name="posts", blank=True)
    roles_needed = models.ManyToManyField(
        Role, through="PostRole", related_name="posts", blank=True
    )

    objects = ActivePostManager()
    all_objects = models.Manager.from_queryset(PostQuerySet)()

    class Meta:
        verbose_name = _("post")
        verbose_name_plural = _("posts")
        constraints = [
            # QA finding 10. Both the stale job and feed ranking assume this, and
            # a seed bug that violated it would otherwise ship silently.
            models.CheckConstraint(
                condition=Q(last_activity_at__gte=F("published_at")),
                name="post_activity_after_publication",
            ),
        ]
        indexes = [
            # ── The two feed indexes ──────────────────────────────────────────
            # Each matches its ORDER BY column for column, so the feed is a forward
            # index scan with no sort node.
            #
            # `-id` is the unique tiebreaker (PF-1). Without it the sort tuple is
            # not unique — the seed writes arbitrary published_at values across 90
            # days, so collisions are near-certain in the demo corpus — and any
            # pagination that cannot fully order rows will repeat some cards and
            # silently drop others as the user scrolls. Worse on "most sparked",
            # where spark_count mutates while the user is paginating.
            models.Index(
                fields=["is_stale", "-published_at", "-id"],
                condition=_FEED_CONDITION,
                name="post_feed_newest_idx",
            ),
            models.Index(
                fields=["is_stale", "-spark_count", "-published_at", "-id"],
                condition=_FEED_CONDITION,
                name="post_feed_sparked_idx",
            ),
            # ── Discovery filters ─────────────────────────────────────────────
            # Each leads with the filtered column then `is_stale`, so a filtered
            # view keeps the stale demotion instead of silently dropping it — which
            # matters most here, because a filtered result set is small enough that
            # a stale post at the top is the whole screen (D3).
            models.Index(
                fields=["city_slug", "is_stale", "-published_at"],
                condition=_FEED_CONDITION,
                name="post_filter_city_idx",
            ),
            models.Index(
                fields=["commitment", "is_stale", "-published_at"],
                condition=_FEED_CONDITION,
                name="post_filter_commitment_idx",
            ),
            models.Index(
                fields=["stage", "is_stale", "-published_at"],
                condition=_FEED_CONDITION,
                name="post_filter_stage_idx",
            ),
            # ── Search ────────────────────────────────────────────────────────
            GinIndex(fields=["search_vector"], name="post_search_vector_gin"),
            GinIndex(fields=["keywords"], name="post_keywords_gin"),
            GinIndex(fields=["title"], opclasses=["gin_trgm_ops"], name="post_title_trgm"),
            # ── Everything else ───────────────────────────────────────────────
            models.Index(fields=["author", "-published_at"], name="post_author_idx"),
            models.Index(fields=["status", "-published_at"], name="post_status_idx"),
            # The stale-post nudge job's candidate set, partial on exactly the
            # predicate the job uses (TS-11). Free now, a migration later.
            models.Index(
                fields=["last_activity_at"],
                condition=Q(deleted_at__isnull=True, is_stale=False, status=PostStatus.LOOKING),
                name="post_stale_candidates_idx",
            ),
        ]

    def __str__(self):
        return self.title

    def touch_activity(self):
        """Mark the post alive again. The ONLY way `last_activity_at` is written.

        Nothing else in the original document ever set `is_stale` back to `False`
        (PF-2), so an author who answered the nudge, edited the post and collected
        five sparks and two comments would sit at the bottom of every feed forever.
        It never errors and the post is still visible, so it reads as "the feed is a
        bit weird" and nobody ever finds it.

        It is cross-seat, which is what made it certain rather than likely: Social
        bumps on comment, Posts on edit and status change, Trust & Safety on nudge
        response. Three seats who cannot see each other's chats would each have
        implemented part of it, and the part everyone forgets is the flag.

        `nudged_at` is cleared too (TS-10). Without that a post gets exactly one
        nudge in its entire life: revived in month 2, abandoned in month 3, never
        nudged again, silently.

        Uses `.update()`, not `.save()` — `updated_at` is `auto_now`, and a system
        write through `save()` would stamp "edited just now" on a post whose author
        did nothing (PF-11).
        """
        Post.all_objects.filter(pk=self.pk).update(
            last_activity_at=Now(), is_stale=False, nudged_at=None
        )


class PostTag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="post_tags")
    # PROTECT — never let deleting a tag silently strip it off every post using it.
    tag = models.ForeignKey(Tag, on_delete=models.PROTECT, related_name="post_tags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "tag"], name="uniq_post_tag"),
        ]
        indexes = [
            models.Index(fields=["tag", "post"], name="posttag_tag_idx"),
        ]

    def __str__(self):
        return f"{self.post_id} tagged {self.tag_id}"


class PostRole(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="post_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="post_roles")
    # "React dev, ~5 hrs/week". The difference between "Android dev" and "Android
    # dev, evenings, ~5 hrs/week" is most of what a joiner needs to self-select.
    note = models.CharField(_("note"), max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "role"], name="uniq_post_role"),
        ]
        indexes = [
            models.Index(fields=["role", "post"], name="postrole_role_idx"),
        ]

    # Deliberately NO `is_filled` and no application state. Roles-needed is
    # information and a filter, not a workflow (spec §2.3) — adding status here
    # would turn team-forming into an application process, which the product
    # explicitly refuses to be.

    def __str__(self):
        return f"{self.post_id} needs {self.role_id}"


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(_("image"), upload_to="posts/", blank=True)
    # Same gap `Profile.avatar_url` closed, one model over (QA finding 3). Without
    # it the seed cannot put a single image on the demo site: uploading from a
    # management command is slow, credential-dependent and not idempotent. The demo
    # would ship 45 text-only posts and the crochet-business case — the one the
    # spec names by hand — would have no picture.
    image_url = models.URLField(_("image URL"), blank=True)
    # Often the only text an image ever gets, and the accessible description too.
    caption = models.CharField(_("caption"), max_length=140, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["post", "order"], name="postimage_post_order_idx"),
        ]

    def __str__(self):
        return f"Image {self.order} on post {self.post_id}"

    @property
    def display_url(self) -> str:
        """Uploaded image wins; falls back to the seeded external URL."""
        if self.image:
            return self.image.url
        return self.image_url or ""


# ── Social layer (§2.6–2.8) ──────────────────────────────────────────────────
# These live in `posts` because their lifecycle is the post's, but behaviour over
# them belongs to the Social seat.


class CommentQuerySet(BlockAwareQuerySetMixin, models.QuerySet):
    block_filter_field = "author"


class ActiveCommentManager(models.Manager.from_queryset(CommentQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Comment(models.Model):
    """Flat comments (spec §4.4). Deletable, not editable.

    Comments are first-class: people who don't want to join still add value by
    suggesting things (spec §2.5).
    """

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    body = models.TextField(_("body"))
    spark_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    # Kept even though comments are not editable: moderation redaction touches the
    # row, and `auto_now` is free. No `is_edited` — there is nothing to flag.
    updated_at = models.DateTimeField(auto_now=True)
    # Soft delete: a deleted comment may still be attached to an open report.
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveCommentManager()
    all_objects = models.Manager.from_queryset(CommentQuerySet)()

    class Meta:
        verbose_name = _("comment")
        verbose_name_plural = _("comments")
        indexes = [
            models.Index(
                fields=["post", "created_at"],
                condition=Q(deleted_at__isnull=True),
                name="comment_post_idx",
            ),
            models.Index(fields=["author", "-created_at"], name="comment_author_idx"),
        ]

    def __str__(self):
        return f"Comment<{self.pk}> on {self.post_id}"

    # Deliberately NO `parent` field. Nested threads are Phase 2, and adding a
    # nullable self-FK then is a one-line, zero-downtime migration. Not carrying
    # speculative structure now.


class PostSpark(models.Model):
    """The reaction. Never "like" — sparking gives an idea energy and ranks the feed.

    Two concrete models (this and `CommentSpark`) rather than one generic
    ContentType spark: real FK integrity, `UniqueConstraint` that actually works,
    and counting is a plain indexed count. A generic model buys flexibility we have
    no use for — there will never be a third sparkable thing in v1.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_sparks"
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="sparks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "post"], name="uniq_post_spark"),
        ]
        indexes = [
            # Real work, not a duplicate: the unique constraint leads on `user`,
            # so it cannot serve "how many sparks does this post have".
            models.Index(fields=["post"], name="postspark_post_idx"),
            models.Index(fields=["user", "-created_at"], name="postspark_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} sparked post {self.post_id}"


class CommentSpark(models.Model):
    """Sparks on comments — in v1, per spec §4.4 ("on posts *and* comments")."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comment_sparks"
    )
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="sparks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "comment"], name="uniq_comment_spark"),
        ]
        indexes = [
            models.Index(fields=["comment"], name="commentspark_comment_idx"),
            models.Index(fields=["user", "-created_at"], name="commentspark_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} sparked comment {self.comment_id}"


class SavedPostQuerySet(BlockAwareQuerySetMixin, models.QuerySet):
    # `post__author`, NOT `user` (S9). ADR-0003's original wording said "<author
    # field>", and the naive reading here is `user` — which is always the viewer,
    # so the Saved screen would have filtered nothing and silently rendered blocked
    # authors' posts. That is a privacy leak, not a cosmetic bug.
    block_filter_field = "post__author"


class SavedPost(models.Model):
    """A private bookmark. Unlike a spark, never visible to anyone else."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_posts"
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="saves")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SavedPostQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "post"], name="uniq_saved_post"),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="savedpost_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} saved post {self.post_id}"
