from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Admin is the moderation surface (product-spec.md §4.7), so it is worth
    keeping accurate rather than accepting the default that still shows
    first_name/last_name — fields this model doesn't have."""

    list_display = ("username", "email", "display_name", "is_active", "is_demo", "date_joined")
    list_filter = ("is_active", "is_staff", "is_demo", "is_public_demo", "date_joined")
    search_fields = ("username", "email", "display_name")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login", "last_seen_at")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Profile"), {"fields": ("email", "display_name")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (_("Demo"), {"fields": ("is_demo", "is_public_demo")}),
        (
            _("Lifecycle"),
            {"fields": ("deletion_requested_at", "last_seen_at", "last_login", "date_joined")},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "display_name", "password1", "password2"),
            },
        ),
    )
