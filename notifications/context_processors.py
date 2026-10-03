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
    """`{"unread_alerts": n}` for a signed-in viewer, nothing for anyone else.

    **Anonymous returns an empty dict before any I/O**, which matters more than
    it looks: the public feed and the landing page are the most-hit queries in
    the app and `CONTRIBUTING.md` rule 7 makes them non-negotiable, so they must not
    acquire a count query just because a context processor exists. The tab bar
    defaults the value to 0, and anonymous visitors get
    `components/_guest_tab_bar.html` anyway, which has no bell.

    `getattr` rather than `request.user` directly: a context processor also runs
    for responses rendered outside the auth middleware's reach — error pages
    among them — and an `AttributeError` there would turn a 404 into a 500.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    return {"unread_alerts": unread_count(user)}
