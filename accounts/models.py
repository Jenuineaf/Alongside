"""Accounts models.

**Migration 0001 contains `User` and nothing else.** Swapping `AUTH_USER_MODEL`
after other tables exist is brutal in Django, so it goes first and alone —
`roadmap.md` ground rule 2, `data-model.md` §10.

`Profile`, `ProfileSkill`, `ProfileInterest`, `Follow` and `Block` arrive in
`accounts` 0002, after `posts` 0001 creates `Tag` and `Role` (they are foreign
key targets). Adding them here now would create a circular dependency between
the two apps' first migrations.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

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

    # We use display_name instead. Removing them keeps the admin and every form
    # honest about which field is the real one.
    first_name = None
    last_name = None

    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-date_joined"]

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        # The validator enforces lowercase, but normalising here means a
        # username created outside a form (allauth's social adapter, the seed
        # command, a shell) can never produce a case-variant duplicate.
        if self.username:
            self.username = self.username.lower().strip()
        self.email = self.__class__.objects.normalize_email(self.email)
        super().save(*args, **kwargs)

    @property
    def name(self) -> str:
        """What the UI renders. Never blank.

        Every seat displaying a user calls this rather than branching on
        `display_name` — including for anonymised accounts, which must render as
        `[deleted]` everywhere (ADR-0001).
        """
        if self.deletion_requested_at and not self.is_active:
            return "[deleted]"
        return self.display_name or self.username
