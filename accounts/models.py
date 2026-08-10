"""Accounts models.

**Migration 0001 contains `User` and nothing else.** Swapping `AUTH_USER_MODEL`
after other tables exist is brutal in Django, so it goes first and alone —
`roadmap.md` ground rule 2, `data-model.md` §10.

`Profile`, `ProfileSkill`, `ProfileInterest`, `Follow` and `Block` arrive in
`accounts` 0002, after `posts` 0001 creates `Tag` and `Role` (they are foreign
key targets). Adding them here now would create a circular dependency between
the two apps' first migrations.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from accounts.blocking import BlockAwareQuerySetMixin
from accounts.validators import (
    username_format_validator,
    validate_username_not_reserved,
)


class User(AbstractUser):
    """Identity and auth only — see `data-model.md` §1.1.

    Deliberately thin. Anything that will churn during the build lives on
    `Profile` (0002), because this is the one table that is genuinely painful to
    change later.
    """

    # AbstractUser gives us: password, last_login, is_superuser, is_staff,
    # is_active, date_joined, and the groups/permissions M2Ms.

    username = models.CharField(
        _("username"),
        max_length=30,
        unique=True,
        db_index=True,
        validators=[username_format_validator, validate_username_not_reserved],
        help_text=_("3–30 characters. Lowercase letters, numbers and underscores."),
        error_messages={"unique": _("That username is taken.")},
    )
    email = models.EmailField(
        _("email address"),
        unique=True,
        db_index=True,
        error_messages={"unique": _("An account with that email already exists.")},
    )
    display_name = models.CharField(
        _("display name"),
        max_length=60,
        blank=True,
        help_text=_("Shown on cards and profiles. Falls back to the username."),
    )

    # Cheap to carry now; Phase 2's "usually replies within a day" signal needs
    # it and backfilling it later would mean starting from zero history.
    last_seen_at = models.DateTimeField(_("last seen"), null=True, blank=True)

    # Two flags, two jobs — data-model.md §1.1.1. Collapsing them breaks either
    # the seed or the demo account; the reasoning is in the doc.
    is_demo = models.BooleanField(
        _("seed data"),
        default=False,
        help_text=_("Created by seed_demo. Only these rows are removed by --reset."),
    )
    is_public_demo = models.BooleanField(
        _("public demo account"),
        default=False,
        help_text=_(
            "Credentials are published on the login screen, so this account is "
            "read-mostly: it can browse, spark and save, but not post, comment or DM."
        ),
    )

    # ADR-0001 — deletion anonymises after a 30-day grace window.
    deletion_requested_at = models.DateTimeField(
        _("deletion requested"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Start of the 30-day grace window. Null means not deleting."),
    )
    # Requested independently by Accounts (ACC-1), Messaging (M1) and QA (finding 1).
    # Without it, "has this account been scrubbed" is inferred from
    # `deletion_requested_at AND NOT is_active` — which is wrong in a state that
    # really happens: request deletion on day 0, get banned by moderation on day 3,
    # and every card, comment and conversation header renders `[deleted]` while the
    # bio, avatar and links are all still intact and on screen.
    #
    # It is also what makes ADR-0001's idempotency requirement testable: the job
    # selects `deletion_requested_at <= now-30d AND anonymised_at IS NULL`, so a
    # run that fails partway is retried instead of being skipped forever.
    anonymised_at = models.DateTimeField(
        _("anonymised"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Set by the scrub job. Null means the account still has its data."),
    )

    # We use display_name instead. Removing them keeps the admin and every form
    # honest about which field is the real one.
    first_name = None
    last_name = None

    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        # No `ordering` here on purpose (ACC-14). A default ordering applies to
        # joins, subqueries and aggregates — not just the queries that want it —
        # so it turns up inside a GROUP BY and quietly changes the plan. Views
        # that want an order say so.
        indexes = [
            # Fuzzy people search (D4). These live on `User`, not `Profile`,
            # because the two highest-signal fields for finding a person are here
            # — and an AddIndex against `accounts.User` cannot live in a `posts`
            # migration, which is what §10 originally asked for.
            #
            # `username` needs its own trigram index despite being unique: a
            # unique btree serves equality, not `ILIKE '%jen%'`, and people search
            # by handle.
            GinIndex(
                fields=["display_name"],
                opclasses=["gin_trgm_ops"],
                name="user_display_name_trgm",
            ),
            GinIndex(
                fields=["username"],
                opclasses=["gin_trgm_ops"],
                name="user_username_trgm",
            ),
        ]

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        # The validator enforces lowercase, but normalising here means a
        # username created outside a form (allauth's social adapter, the seed
        # command, a shell) can never produce a case-variant duplicate.
        if self.username:
            self.username = self.username.lower().strip()
        # `normalize_email()` lowercases only the DOMAIN, so without the extra
        # `.lower()` `Jeni@x.com` and `jeni@x.com` are two distinct rows under
        # `unique=True` — while allauth compares full-lowercase in several paths.
        # That gives both failure directions at once: duplicate signups that
        # should have collided, and "email already exists" errors on an address
        # the constraint says is free. (ACC-13)
        self.email = self.__class__.objects.normalize_email(self.email or "").lower()
        super().save(*args, **kwargs)

    @property
    def is_anonymised(self) -> bool:
        return self.anonymised_at is not None

    @property
    def name(self) -> str:
        """What the UI renders. Never blank.

        Every seat displaying a user calls this rather than branching on
        `display_name` — including for anonymised accounts, which must render as
        `[deleted]` everywhere (ADR-0001, data-model.md §8.1).
        """
        if self.anonymised_at:
            return "[deleted]"
        return self.display_name or self.username


class ProfileQuerySet(BlockAwareQuerySetMixin, models.QuerySet):
    # People search surfaces other users, so it needs the block filter. The path
    # from Profile to the user whose visibility matters is `user` — see the mapping
    # table in accounts/blocking.py.
    block_filter_field = "user"


class Profile(models.Model):
    """Everything about a person that isn't identity or auth.

    Split from `User` deliberately (§1.2): this is the table that churns during the
    build, and `User` is the one Django makes painful to alter. Created in the same
    transaction as the user via a `post_save` receiver, so every query that renders
    a person can rely on `select_related("profile")`.
    """

    class Purpose(models.TextChoices):
        POST = "post", _("Post an idea")
        FIND = "find", _("Find something to join")
        BOTH = "both", _("Both")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="profile",
    )

    # Two avatar fields on purpose (§1.2.1). `avatar` holds an asset we own;
    # `avatar_url` holds an external one. The seed needs the latter — uploading 20
    # images from a management command is slow, credential-dependent and not
    # idempotent, which breaks the re-runnable contract in testing.md §7.4.
    avatar = models.ImageField(_("avatar"), upload_to="avatars/", blank=True)
    avatar_url = models.URLField(_("avatar URL"), blank=True)

    bio = models.TextField(_("bio"), blank=True)
    headline = models.CharField(_("headline"), max_length=120, blank=True)
    occupation = models.CharField(_("occupation"), max_length=120, blank=True)

    # The entire input to Home tier 2 (ADR-0004). An ordinary topic tag — there is
    # no separate "field" kind, because partitioning the vocabulary is exactly what
    # made that tier structurally incapable of returning a row.
    field_tag = models.ForeignKey(
        "posts.Tag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profiles_in_field",
    )

    purpose = models.CharField(_("purpose"), max_length=10, choices=Purpose.choices, blank=True)

    city = models.CharField(_("city"), max_length=80, blank=True)
    city_slug = models.SlugField(_("city slug"), max_length=80, blank=True)
    is_remote_friendly = models.BooleanField(_("remote friendly"), default=True)

    work_done = models.TextField(_("work done so far"), blank=True)

    # The symmetric case to Post.custom_roles: a skill that isn't on the curated
    # list. Searchable, never filterable (ADR-0004).
    custom_skills = ArrayField(models.CharField(max_length=50), default=list, blank=True, size=3)

    github_url = models.URLField(_("GitHub"), blank=True)
    portfolio_url = models.URLField(_("portfolio"), blank=True)
    website_url = models.URLField(_("website"), blank=True)

    # Means "reached the end of the flow by ANY path, including skipping every
    # step" — not "answered the questions". Whether they answered is derived from
    # the fields themselves. That distinction is what lets us re-prompt someone who
    # bounced mid-flow without nagging someone who deliberately skipped.
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

    follower_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    post_count = models.PositiveIntegerField(default=0)

    # Contents pinned in data-model.md §1.2 (D10):
    #   user.display_name + user.username                        A
    #   headline + occupation + custom_skills + skills.name      B
    #   bio + work_done                                          C
    #   city                                                     D
    # Two of those live on `User`, so Accounts must trigger a rebuild when
    # `display_name` or `username` changes — otherwise renaming yourself makes you
    # unfindable under the new name, with no error anywhere.
    search_vector = SearchVectorField(null=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    skills = models.ManyToManyField(
        "posts.Role", through="ProfileSkill", related_name="profiles", blank=True
    )
    interests = models.ManyToManyField(
        "posts.Tag", through="ProfileInterest", related_name="interested_profiles", blank=True
    )

    objects = ProfileQuerySet.as_manager()

    class Meta:
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")
        # No explicit Index on `field_tag` or `city_slug` (ACC-4): the FK creates
        # its own index and SlugField sets db_index=True by default, so declaring
        # them here would build a second, identical btree.
        indexes = [
            GinIndex(fields=["search_vector"], name="profile_search_vector_gin"),
        ]

    def __str__(self):
        return f"Profile<{self.user_id}>"

    @property
    def avatar_display_url(self) -> str:
        """The one place avatar precedence is decided.

        An uploaded image always wins over a generated one. Seats call this rather
        than branching in a template, so the seed's generated avatars and real
        uploads render through identical code.
        """
        if self.avatar:
            return self.avatar.url
        return self.avatar_url or ""


class ProfileSkill(models.Model):
    """A role this person can fill. Explicit through-model, per §1.3."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="skill_links")
    # PROTECT, matching PostRole (§2.4) — ACC-3. Deleting a Role from the admin
    # must not silently strip that skill off every profile claiming it.
    role = models.ForeignKey("posts.Role", on_delete=models.PROTECT, related_name="profile_skills")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "role"], name="uniq_profile_skill"),
        ]
        indexes = [
            # "who can do X" — the reverse direction, which the unique
            # constraint's leading column does not serve.
            models.Index(fields=["role", "profile"], name="profileskill_role_idx"),
        ]

    def __str__(self):
        return f"{self.profile_id} can do {self.role_id}"


class ProfileInterest(models.Model):
    """A topic this person wants to see. Drives Home tier 1."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="interest_links")
    tag = models.ForeignKey("posts.Tag", on_delete=models.PROTECT, related_name="profile_interests")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "tag"], name="uniq_profile_interest"),
        ]
        indexes = [
            models.Index(fields=["tag", "profile"], name="profileinterest_tag_idx"),
        ]

    def __str__(self):
        return f"{self.profile_id} interested in {self.tag_id}"


class Follow(models.Model):
    """One-way, instant, no approval (spec §2.2, §4.4).

    Hard-deleted on unfollow, on block (both directions), and on anonymisation —
    and every one of those deletes must decrement `follower_count` /
    `following_count` in the same transaction (§7.1, ACC-6).
    """

    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following_edges"
    )
    following = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follower_edges"
    )
    # The optional follow note — "I'd want the backend role". A real database
    # limit, because it is a CharField and not a TextField(N); see §0.
    note = models.CharField(_("note"), max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "following"], name="uniq_follow"),
            models.CheckConstraint(condition=~Q(follower=F("following")), name="follow_not_self"),
        ]
        indexes = [
            models.Index(fields=["following", "-created_at"], name="follow_followers_idx"),
            models.Index(fields=["follower", "-created_at"], name="follow_following_idx"),
        ]

    def __str__(self):
        return f"{self.follower_id} -> {self.following_id}"


class Block(models.Model):
    """Full mutual invisibility (ADR-0002).

    The row is one-way; the effect is symmetric and global. Resolution lives in
    `accounts/blocking.py` — nothing should query this table directly except that
    module and the Settings block list, which is the one authenticated surface where
    the filter must NOT apply (or there is no way to unblock anyone).

    Two things here that are deliberate and must not be "fixed":

    * Blocking never deletes a message or a conversation. Hiding is a filter, so
      unblocking restores the thread with no restore code path at all.
    * Block is a soft barrier, not an access control. The feed is public, so a
      blocked person can log out and read public content. That is an accepted
      consequence of `CLAUDE.md` rule 7, and the wrong fix for it is a login wall.
    """

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_made"
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_received"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block"),
            models.CheckConstraint(condition=~Q(blocker=F("blocked")), name="block_not_self"),
        ]
        # No explicit Index on either column (ACC-4) — both are FKs and therefore
        # already indexed, which is exactly what `blocked_user_ids()` needs for its
        # two-direction lookup.

    def __str__(self):
        return f"{self.blocker_id} blocks {self.blocked_id}"
