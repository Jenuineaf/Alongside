"""The bell badge, on every page that has a tab bar.

`components/_tab_bar.html` reads `unread_alerts` from the template context and
hides the badge when it is 0. The bar renders on every authenticated screen, so
the count cannot come from each view — fourteen views would each have to
remember it, and the one that forgot would silently show no badge.

Registered in `config/settings/base.py` (the Architect's file); the function is
this seat's.
"""

from notifications.services import unread_count


def unread_alerts(request):
    """Both tab-bar badges for a signed-in viewer, nothing for anyone else.

    It carries `unread_messages` as well as `unread_alerts` despite the name —
    deliberately, because the alternative is a second context processor and a
    second line in `TEMPLATES`, which lives in the Architect's
    `config/settings/base.py`. One registered callable, two counts, one place to
    look when a badge is wrong.

    **Anonymous returns an empty dict before any I/O**, which matters more than
    it looks: the public feed and the landing page are the most-hit queries in
    the app and `CLAUDE.md` rule 7 makes them non-negotiable, so they must not
    acquire two count queries just because a context processor exists. The tab
    bar defaults both to 0, and anonymous visitors get
    `components/_guest_tab_bar.html` anyway, which has neither badge.

    `getattr` rather than `request.user` directly: a context processor also runs
    for responses rendered outside the auth middleware's reach — error pages
    among them — and an `AttributeError` there would turn a 404 into a 500.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    return {
        "unread_alerts": unread_count(user),
        "unread_messages": _unread_messages(user),
    }


def _unread_messages(user) -> int:
    """How many conversations have something unread. Threads, not messages.

    A count of conversations rather than of messages, because that is what the
    badge means next to a Messages tab — "three people are waiting on you", not
    "there are thirty unread lines". `participant_unread_idx` is partial on
    exactly `unread_count > 0`, so this touches only the handful of rows that
    qualify.

    **Block-filtered** (M17): ADR-0003's own test enumerates list URLs, and a
    badge is not a list URL — so without this the badge happily counts a
    conversation with somebody the viewer has blocked, on every page, while that
    test stays green. It is the leak that ADR-0003's coverage is shaped not to
    catch.
    """
    from messaging.models import Conversation, ConversationParticipant

    visible = Conversation.objects.visible_to(user).values("pk")

    return (
        ConversationParticipant.objects.filter(
            user=user, unread_count__gt=0, is_archived=False, conversation__in=visible
        ).count()
    )
