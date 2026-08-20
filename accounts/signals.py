"""Account lifecycle signals.

Two receivers: every user gets a profile, and logging in cancels a pending
deletion (ADR-0001).
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from accounts.models import Profile


@receiver(post_save, sender=get_user_model())
def ensure_profile(sender, instance, created, **kwargs):
    """Every user has a profile, from the moment they exist.

    `data-model.md` §1.2 and the `Profile` docstring both promise this, and a
    lot of other seats' code depends on it: `select_related("profile")` returning
    `None` is an `AttributeError` in a template, which renders as a blank region
    rather than an error anyone notices.

    `get_or_create` rather than `create` because `post_save` also fires on every
    update, and because `testing.md` §2.2 asserts a profile survives
    `get_or_create` being called twice.

    Not guarded on `created`: a user row that predates this receiver — a fixture,
    a shell session, a seed run from an older revision — would otherwise never
    get one, and the failure would surface much later as a missing profile on
    one specific account.
    """
    Profile.objects.get_or_create(user=instance)


CANCELLED_MESSAGE = _(
    "Welcome back. Your account was scheduled for deletion — that's now cancelled."
)


@receiver(user_logged_in)
def cancel_pending_deletion(sender, request, user, **kwargs):
    """Logging in during the 30-day window cancels the deletion (ADR-0001).

    Hung off `user_logged_in` rather than allauth's `post_login` so it also
    covers the admin login and anything else that authenticates — there must be
    no way to get a session on an account that is still counting down.

    An anonymised account cannot reach this: the scrub sets `is_active=False`,
    which `ModelBackend` refuses to authenticate. The guard is here anyway
    because a `deletion_requested_at` that survived a scrub would otherwise be
    silently cleared, destroying the only record of when the account went.

    The user is told. Silently reversing a deletion someone deliberately asked
    for is worse than not offering the grace window at all.
    """
    if user.deletion_requested_at is None or user.anonymised_at is not None:
        return

    # `update()` rather than `save()`: it writes one column, skips the model's
    # save path, and cannot clobber a concurrent write to another field.
    updated = (
        get_user_model()
        .objects.filter(pk=user.pk, anonymised_at__isnull=True)
        .update(deletion_requested_at=None)
    )
    if not updated:
        return

    user.deletion_requested_at = None

    # Only tell them if there is somewhere to put the message. `user_logged_in`
    # also fires from places that never ran `MessageMiddleware` — `force_login`
    # in tests, a management command, a shell session — and `messages.info()`
    # raises `MessageFailure` there. Cancelling the deletion is the important
    # half and must not be lost because the notice had nowhere to go.
    if request is not None and hasattr(request, "_messages"):
        messages.info(request, CANCELLED_MESSAGE)
