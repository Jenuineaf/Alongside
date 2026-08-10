from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Accounts & Profiles"

    def ready(self):
        # Imported for the side effect of registering the receivers. Kept in
        # `ready()` rather than at module scope because importing models before
        # the app registry is populated is the classic Django import loop.
        from accounts import signals  # noqa: F401
