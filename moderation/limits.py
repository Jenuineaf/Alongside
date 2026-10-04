"""Rate limits — the policy in one place, and a guard against taking the site down.

Spec §4.7 names posts, DMs and follows. **Reports are added** at the Trust &
Safety seat's request: the conditional unique constraint only stops duplicate
reports of the *same* target, so one account can still flood the queue with
fifty different ones — a moderation denial-of-service with no other defence.
Decision H (sign-in required to report) is what lets that limit key on `user`
rather than on an IP that Render's proxy may share between everybody.

**The rates themselves are not in any approved document.** They are set here, as
named constants, deliberately generous: a limit that catches a real spammer and
never a real person. If Jeni wants different numbers this is the one file to
edit. Flagged in `docs/phase-6-trust.md` as awaiting a ruling.

## The production risk this module exists for

`render.yaml` does not guard `REDIS_URL`, and `CACHES["default"]` is Redis in
production. django-ratelimit reads the cache on **every** post, DM, follow and
report — so an unreachable Redis turns a rate limiter into a site-wide 500 on
every write path, backed by an external service nobody is paging about
(`trust-safety.md` §2 raises this as a "whole site 500s" risk rather than a "one
feature degrades" one).

`fail_open` is the answer: a cache that errors lets the request through and logs
it. That is the right trade for this product — the cost of letting a spammer
past during a Redis outage is some spam; the cost of failing closed is that
nobody can post, comment, follow or report at all, and the cause is invisible
from the traceback.
"""

import logging
from functools import wraps

from django_ratelimit.core import is_ratelimited
from django_ratelimit.exceptions import Ratelimited

logger = logging.getLogger(__name__)

# ── The policy ──────────────────────────────────────────────────────────────
#
# Keyed on `user` everywhere. Every rate-limited action here is login-required,
# so there is no anonymous path to key on an IP — which also sidesteps the
# shared-proxy-IP problem entirely (TS-9).

RATE_POST = "10/h"  # publishing ideas
RATE_COMMENT = "30/h"  # comments are conversation; the limit is for scripts
RATE_FOLLOW = "60/h"  # following is one tap and a normal binge is dozens
RATE_MESSAGE = "60/h"  # a real conversation is many messages in a few minutes
RATE_REPORT = "20/h"  # the moderation-DoS guard

# M20 — the limit that actually matters for DMs, and it is not the message rate.
# With no request gate, anyone can open a thread with anyone, so the abuse
# pattern is **fifty cold first contacts**, not fifty messages inside one
# conversation. Those are opposite shapes: a real conversation is many messages
# to one person in a few minutes, which `RATE_MESSAGE` has to allow, while this
# is few messages to many people, which it has to refuse. Tighter on purpose.
RATE_CONVERSATION = "15/h"


def rate_limit(rate: str, *, key: str = "user", method: str = "POST"):
    """`django_ratelimit.decorators.ratelimit`, but it cannot 500 the site.

    Same contract as the library's own decorator — exceeded means `Ratelimited`,
    which Django turns into a 429 through the handler registered in
    `config/urls.py` — except that an exception from the **cache backend** is
    swallowed and the request is allowed.

    The `except Exception` is deliberate and is the whole point of the wrapper.
    The cache backend can raise anything from `ConnectionError` to a socket
    timeout depending on which client is installed, and enumerating those is how
    this grows a hole the day the backend changes. `Ratelimited` is re-raised
    first so a genuine limit is never confused with an outage.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            try:
                limited = is_ratelimited(
                    request=request,
                    group=f"{view.__module__}.{view.__name__}",
                    key=key,
                    rate=rate,
                    method=method,
                    increment=True,
                )
            except Ratelimited:
                raise
            except Exception:
                # Fail open, loudly. This is the Redis-is-down path, and it is
                # the one thing that must not become a site-wide 500.
                logger.exception(
                    "Rate limiter unavailable; allowing request to %s", request.path
                )
                return view(request, *args, **kwargs)

            if limited:
                raise Ratelimited()

            return view(request, *args, **kwargs)

        return wrapper

    return decorator
