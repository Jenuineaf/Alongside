"""Username validation.

Pure functions, no database — QA unit-tests these exhaustively without Postgres
(`testing.md` §2.1).
"""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

USERNAME_REGEX = r"^[a-z0-9_]{3,30}$"

username_format_validator = RegexValidator(
    regex=USERNAME_REGEX,
    message=_(
        "Usernames use lowercase letters, numbers and underscores only, "
        "and must be 3–30 characters."
    ),
    code="invalid_username",
)

# Names that would collide with a URL path, impersonate the platform, or look
# official. Usernames appear at /u/<username>, but several of these are reserved
# against future top-level routes too — it is far cheaper to reserve them now
# than to rename a real user's account later.
RESERVED_USERNAMES = frozenset(
    {
        # Routing
        "about",
        "accounts",
        "admin",
        "api",
        "auth",
        "blog",
        "contact",
        "css",
        "dashboard",
        "docs",
        "explore",
        "feed",
        "healthz",
        "help",
        "home",
        "internal",
        "js",
        "legal",
        "login",
        "logout",
        "media",
        "messages",
        "new",
        "notifications",
        "onboarding",
        "post",
        "posts",
        "privacy",
        "profile",
        "register",
        "reset",
        "robots",
        "saved",
        "search",
        "settings",
        "signin",
        "signup",
        "static",
        "status",
        "support",
        "tag",
        "tags",
        "terms",
        "u",
        "user",
        "users",
        # Impersonation
        "alongside",
        "alongsideapp",
        "moderator",
        "mod",
        "official",
        "root",
        "staff",
        "system",
        "team",
        # Reserved by ADR-0001 — anonymised accounts render as [deleted].
        "deleted",
    }
)


def validate_username_not_reserved(value: str) -> None:
    if value and value.lower() in RESERVED_USERNAMES:
        raise ValidationError(
            _("That username is reserved. Please choose another."),
            code="reserved_username",
        )
