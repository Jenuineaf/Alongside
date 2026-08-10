"""Block resolution — the one place that answers "who can this viewer not see".

Implements [ADR-0003](../docs/adr/0003-block-filter-strategy.md).

ADR-0002 makes blocking **symmetric and global**: a single `Block` row hides each
user from the other everywhere. That is the right product call and it puts a filter
on roughly a dozen read paths owned by six seats who cannot see each other's chats.
"Every seat remembers to filter" is not a design, so the filter lives here and every
seat calls `.visible_to(user)` instead of hand-writing an exclude.

Three properties this module has to preserve, in order of importance:

1. **Anonymous is free.** `blocked_user_ids(AnonymousUser)` returns an empty
   frozenset without touching Redis or Postgres. The public feed is the most-hit
   query in the app and `CONTRIBUTING.md` rule 7 makes it non-negotiable — it must carry
   no visibility logic at all.
2. **An empty block set is also free** (D11). The overwhelming majority of logged-in
   users have blocked nobody; without a short-circuit every authenticated feed query
   would carry `.exclude(author_id__in=[])` forever to filter nothing.
3. **Both directions.** The row is one-way; the effect is not. Every query here is
   the union of "blocked by me" and "blocked me".
"""

from django.core.cache import cache

CACHE_KEY = "blocks:v1:{user_id}"

# A backstop, not the mechanism. Invalidation is explicit and transactional; this
# only bounds the damage if an invalidation is ever missed. Long enough to be worth
# caching, short enough that a missed invalidation is a bad hour rather than a bad
# week.
CACHE_TTL = 60 * 60

# Attribute used to memoise on the user instance. Django builds one `request.user`
# per request, so this collapses the several `visible_to()` calls a single page
# makes into one cache read.
_REQUEST_ATTR = "_alongside_blocked_ids"


def blocked_user_ids(user) -> frozenset[int]:
    """Ids the given viewer must not see, in either direction.

    Returns an empty frozenset for anonymous or `None` users, before any I/O.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()

    cached_on_instance = getattr(user, _REQUEST_ATTR, None)
    if cached_on_instance is not None:
        return cached_on_instance

    key = CACHE_KEY.format(user_id=user.pk)
    ids = cache.get(key)
    if ids is None:
        ids = _fetch(user.pk)
        cache.set(key, ids, CACHE_TTL)
    else:
        ids = frozenset(ids)

    try:
        setattr(user, _REQUEST_ATTR, ids)
    except AttributeError:  # pragma: no cover - defensive, e.g. a frozen stub
        pass
    return ids


def _fetch(user_id: int) -> frozenset[int]:
    """One query, both directions, using the two FK indexes on `Block`."""
    from accounts.models import Block

    pairs = Block.objects.filter(blocker_id=user_id).values_list("blocked_id", flat=True)
    reverse = Block.objects.filter(blocked_id=user_id).values_list("blocker_id", flat=True)
    return frozenset(pairs) | frozenset(reverse)


def invalidate_block_cache(*users_or_ids) -> None:
    """Drop the cached set for every user whose visibility just changed.

    Accepts user instances or bare ids. **Must be called for BOTH users**, inside
    the same `transaction.atomic()` block as the `Block` row write — blocking is
    symmetric, so one row changes two people's view of the product. Missing one
    means the block appears to work for the blocker and not the blocked user, for
    up to `CACHE_TTL`.

    **Pass the acting `request.user` as an instance, not as `request.user.pk`.**
    Clearing the shared cache is not sufficient on its own: `blocked_user_ids()`
    also memoises on the user object, and that memo outlives the cache delete
    within the same request — `refresh_from_db()` does not clear it either. The
    request that *creates* a block would then render its own response from the
    stale set, so the page confirming "you blocked this person" would still show
    that person's posts. Passing the instance is what clears the memo.
    """
    keys = []
    for item in users_or_ids:
        if item is None:
            continue
        if hasattr(item, "pk"):
            user_id = item.pk
            # Drop the per-instance memo so the rest of THIS request sees the
            # change, not just subsequent ones.
            try:
                delattr(item, _REQUEST_ATTR)
            except AttributeError:
                pass
        else:
            user_id = item
        if user_id:
            keys.append(CACHE_KEY.format(user_id=user_id))
    if keys:
        cache.delete_many(keys)


class BlockAwareQuerySetMixin:
    """Supplies `visible_to()` to every model that can surface another user.

    Subclasses declare `block_filter_field` — the lookup path from this model to the
    user whose visibility matters. It is **not** always an "author": ADR-0003's
    original wording said `<author field>`, and Social (S9) and Messaging (M15)
    both showed that the naive reading is wrong for three of the six models it
    listed. `SavedPost` in particular would have filtered on `user`, which is always
    the viewer — so the Saved screen would have filtered nothing and quietly
    rendered blocked authors' posts.

    The mapping now lives on each queryset, next to the model it describes:

    | Model          | `block_filter_field`  |
    |----------------|-----------------------|
    | `Post`         | `author`              |
    | `Comment`      | `author`              |
    | `Profile`      | `user`                |
    | `SavedPost`    | `post__author`        |
    | `Notification` | `actor`               |
    | `Conversation` | `participants__user`  |

    `Message` deliberately has none. In a 1:1 thread the conversation is already
    hidden, so per-message filtering is redundant and the only thing it can produce
    is a half-rendered thread with holes in it.
    """

    block_filter_field: str | None = None

    def visible_to(self, user):
        """Rows this viewer is allowed to see. A no-op for anonymous users."""
        if self.block_filter_field is None:  # pragma: no cover - misconfiguration
            raise NotImplementedError(
                f"{type(self).__name__} must set block_filter_field to use visible_to()."
            )
        blocked = blocked_user_ids(user)
        if not blocked:
            return self
        # `.exclude()`, never `.filter(~Q(...))`. On a multi-valued relation such as
        # `participants__user` those are not equivalent: exclude() builds a subquery
        # and drops the row if ANY related user is blocked (correct), while
        # filter(~Q()) negates per joined row and lets the row back in via the other
        # participant. That is a silent leak in the place ADR-0002 cares most about.
        return self.exclude(**{f"{self.block_filter_field}__in": blocked})
