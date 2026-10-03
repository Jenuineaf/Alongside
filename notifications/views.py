"""Screen 12 — Alerts.

The return loop (roadmap §1.3). Without this screen the notification is just a
number going up; this is where it turns back into a visit.

Private by definition — unlike almost everything else in the product, there is
nothing here an anonymous visitor could be shown, so this is one of the few
`login_required` reads in the app.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Follow
from notifications import services
from notifications.models import Notification, NotificationKind

# The bell is a recent-activity surface, not an archive — and a 90-day prune job
# (§8) means there is no long tail to page through. A cap rather than pagination
# keeps the screen one query.
ALERTS_LIMIT = 50


@require_GET
@login_required
def list_notifications(request):
    """The Alerts list, grouped New / Earlier as the Designer drew it.

    Opening the screen does **not** mark anything read. That is deliberate and
    it is not laziness: both dedup rules key on `is_read=False`, so auto-reading
    on view would mean a second follow from the same person always creates a
    fresh row instead of collapsing into the one above it. "Mark all read" is
    the explicit control in the mockup, and it is also the dedup reset.
    """
    notifications = list(
        Notification.objects.visible_to(request.user)
        .filter(recipient=request.user)
        .select_related("actor", "actor__profile", "post", "comment")
        .order_by("-created_at")[:ALERTS_LIMIT]
    )

    _attach_follow_notes(request.user, notifications)

    return render(
        request,
        "notifications/list.html",
        {
            # Grouped in Python: the rows are already fetched and ordered, so
            # splitting them here costs nothing, while two querysets would be
            # two trips for one screen.
            "unread": [n for n in notifications if not n.is_read],
            "earlier": [n for n in notifications if n.is_read],
            "tab_active": "alerts",
        },
    )


@require_POST
@login_required
def mark_all_read(request):
    """The one control on the screen. Redirects back to it.

    A plain redirect rather than an HTMX partial: every row's appearance changes
    at once, so there is nothing smaller to swap than the screen itself.
    """
    services.mark_all_read(request.user)
    return redirect("notifications:list")


def _attach_follow_notes(user, notifications) -> None:
    """Hang each `new_follower` row's optional note on it, in one query.

    "A follow that came with a note shows the note, because that's the one
    that's actually worth opening" (the Designer, on this screen). The note
    lives on `Follow` rather than on the notification — a notification is an
    event and the note is part of the edge — so it has to be fetched.

    One query for the whole screen, not one per row: a bell with twenty new
    followers would otherwise be twenty queries on the surface people hit most
    (`testing.md` §5.5).

    A missing edge is normal, not an error: they may have unfollowed, or a block
    may have dropped it. The row then renders as a plain "followed you", which
    is still true — it happened.
    """
    actor_ids = {
        n.actor_id for n in notifications if n.kind == NotificationKind.NEW_FOLLOWER and n.actor_id
    }
    if not actor_ids:
        return

    notes = dict(
        Follow.objects.filter(following=user, follower_id__in=actor_ids)
        .exclude(note="")
        .values_list("follower_id", "note")
    )
    if not notes:
        return

    for notification in notifications:
        notification.follow_note = notes.get(notification.actor_id, "")
