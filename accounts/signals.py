"""Account lifecycle signals.

One receiver today: ADR-0001's grace window.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

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
    if request is not None:
        messages.info(request, CANCELLED_MESSAGE)
