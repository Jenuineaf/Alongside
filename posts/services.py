"""Creating, editing and deleting an idea.

A post is the one write in this product that touches four counters, two M2M
tables, a slug that must never change, and the search vector. A view that did it
inline would be the longest function in the codebase and would get one of those
steps wrong — so it lives here, and **views call these**.

The order inside `create_post` is load-bearing and is the thing most likely to
be "tidied" into a bug:

1. the `Post` row, with its slug
2. the M2M rows (tags, roles)
3. the counters
4. `refresh_search_vector()` **last**, because it reads the M2M rows

Swap 2 and 4 and search still works, silently, over a post with no tags and no
roles in its vector — the failure mode `data-model.md` §2.3 exists to warn about.
"""

import secrets

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest, Now
from django.utils.text import slugify

from accounts.models import Profile
from posts.models import (
    MAX_TAGS_PER_POST,
    Post,
    PostRole,
    PostStatus,
    PostTag,
    Role,
    Tag,
)

# Enough entropy that two people publishing the same title in the same second
# don't collide, short enough to keep the URL readable. 4 bytes → 8 hex chars.
SLUG_SUFFIX_BYTES = 4


def build_slug(title: str) -> str:
    """`slugify(title)` plus a short random suffix.

    Generated **once, at creation, and never regenerated** (§2.3): editing a
    title must not rot every link to the post, every notification pointing at
    it, and every DM where somebody pasted the URL.

    The suffix is not decoration. Titles on this product are sentences —
    "I need an actual shop" — so collisions are likely, and `slug` is unique. A
    retry loop on `IntegrityError` would be the alternative; 8 hex chars make it
    unnecessary.

    The slug is truncated to leave room for the suffix, because `slug` is
    `SlugField(160)` and `title` is `CharField(140)`: a long title plus a suffix
    would otherwise overflow the column and fail the insert.
    """
    suffix = secrets.token_hex(SLUG_SUFFIX_BYTES)
    stem = slugify(title)[: 160 - len(suffix) - 1]
    if not stem:
        # A title of only punctuation or only non-Latin script slugifies to "".
        # `slugify` does not transliterate, and a bare suffix is a valid, if
        # ugly, URL — better than a 500 on publish.
        return suffix
    return f"{stem}-{suffix}"


@transaction.atomic
def create_post(author, *, tags=(), roles=(), custom_roles=(), **fields) -> Post:
    """Publish an idea. There are no drafts — a post is live when created (§2.3.1).

    `tags` are free-text names (ADR-0004), created on demand. `roles` are
    `Role` instances or ids from the curated list, because roles are
    exact-match filtered and vocabulary drift breaks a feature.
    """
    post = Post.objects.create(
        author=author,
        slug=build_slug(fields.get("title", "")),
        custom_roles=list(custom_roles),
        **fields,
    )

    _set_tags(post, tags)
    _set_roles(post, roles)

    _bump_profile(author.pk, 1)
    _bump_tag_counts(post, 1)
    _bump_role_counts(post, 1)

    _refresh_search(post)
    return post


@transaction.atomic
def update_post(post, *, tags=None, roles=None, custom_roles=None, **fields) -> Post:
    """Edit an idea. The slug does not change; `last_activity_at` does.

    An author edit is one of the three things that bumps activity
    (`touch_activity`) — it is a direct statement that the author is still
    paying attention, which is the only question the stale nudge asks.

    Counters move by **difference**, not by re-adding: swapping one tag for
    another has to decrement the old one and increment the new one, and the
    naive "+1 for every current tag" leaves `Tag.post_count` climbing on every
    edit. That drift is invisible until a tag page shows a count twice its real
    size.

    `status` moving away from `looking` is deliberately NOT special-cased for
    counters. `Profile.post_count` and `Tag.post_count` count posts that exist,
    not posts in the feed — §7.1 scopes them to `deleted_at IS NULL`, nothing
    more. `Role.usage_count` is the exception, and it is handled below.
    """
    # Status is not an ordinary column: moving in or out of `looking` changes
    # `Role.usage_count` (PF-6a). Routed through `set_status` at the end rather
    # than written here, or editing a post and marking it team-formed in the
    # same submit would leave every role it asked for still counted as live.
    new_status = fields.pop("status", None)

    for field, value in fields.items():
        setattr(post, field, value)
    if custom_roles is not None:
        post.custom_roles = list(custom_roles)

    update_fields = [*fields.keys()]
    if custom_roles is not None:
        update_fields.append("custom_roles")
    if update_fields:
        # `updated_at` is `auto_now`, so it needs to be in the list or Django
        # skips it on a partial save.
        post.save(update_fields=[*update_fields, "updated_at"])

    if tags is not None:
        _retag(post, tags)
    if roles is not None:
        _reassign_roles(post, roles)

    # Last, and deliberately after the role swap: `_reassign_roles` moves
    # counters according to whether the post was live *before* this edit, which
    # is the correct basis, and `set_status` then applies the transition to
    # whatever the role set now is.
    if new_status is not None and new_status != post.status:
        set_status(post, new_status)

    post.touch_activity()
    _refresh_search(post)
    return post


@transaction.atomic
def soft_delete_post(post) -> bool:
    """Remove an idea. Soft, because a report may point at it (§8).

    Everything §7.1 asks for, in one transaction: the author's `post_count`
    down, every tag's `post_count` down, every role's `usage_count` down, and
    the notifications pointing at it deleted (S8).

    Its sparks, saves and comments are deliberately **not** touched — those rows
    survive for moderation, and the post is gone from every list, so their
    counters are moot.

    The guard is in the `UPDATE`, not in Python: two delete requests for the
    same post both see `deleted_at IS NULL`, and only the one that actually
    wrote the row may move the counters.
    """
    updated = Post.all_objects.filter(pk=post.pk, deleted_at__isnull=True).update(
        deleted_at=Now()
    )
    if not updated:
        return False

    _bump_profile(post.author_id, -1)
    _bump_tag_counts(post, -1)
    _bump_role_counts(post, -1)

    from notifications import services as notification_services

    notification_services.drop_for_post(post)
    return True


@transaction.atomic
def set_status(post, status: str) -> Post:
    """The author's own "team formed" / "closed" / "still looking".

    `Role.usage_count` counts **live posts requesting the role** (PF-6a), and a
    `team_formed` post is not requesting anything — so a status change in or out
    of `looking` moves it, while `Profile.post_count` and `Tag.post_count` stay
    put. That asymmetry is the whole reason PF-6a insisted the column's meaning
    be pinned down.

    "Yes, still looking" is also one of the three activity bumps, so coming back
    to `looking` revives the post rather than leaving it at the bottom of the
    feed forever.
    """
    was_live = post.status == PostStatus.LOOKING
    now_live = status == PostStatus.LOOKING

    post.status = status
    post.save(update_fields=["status", "updated_at"])

    # `only_if_live=False`: the transition is already known here, and
    # `_bump_role_counts`' own status guard would read the status we have just
    # written — so releasing a role on "team formed" would check
    # `status == looking`, find it false, and skip the decrement it was called
    # to make. The guard is for callers who need to ask "is this post live";
    # this caller knows.
    if was_live and not now_live:
        _bump_role_counts(post, -1, only_if_live=False)
    elif now_live and not was_live:
        _bump_role_counts(post, 1, only_if_live=False)

    if now_live:
        post.touch_activity()
    return post


# ── Tags and roles ──────────────────────────────────────────────────────────


def resolve_tags(names) -> list[Tag]:
    """Free-text tag names → `Tag` rows, created on demand (ADR-0004).

    Matched on `slug`, not on `name`: "Food Waste", "food waste" and
    "food-waste" are one tag, and without that the vocabulary fragments into
    near-duplicates that no Home-feed match will ever join up.

    `is_curated` stays False for anything created here — only seeded tags appear
    in the onboarding field picker.
    """
    tags: list[Tag] = []
    seen: set[str] = set()

    for name in names:
        cleaned = " ".join(str(name).split())[:40]
        slug = slugify(cleaned)[:40]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        tag, _ = Tag.objects.get_or_create(slug=slug, defaults={"name": cleaned})
        tags.append(tag)
        if len(tags) >= MAX_TAGS_PER_POST:
            break

    return tags


def _set_tags(post, names) -> None:
    for tag in resolve_tags(names):
        PostTag.objects.get_or_create(post=post, tag=tag)


def _set_roles(post, roles) -> None:
    for role in roles:
        role_id = role.pk if isinstance(role, Role) else role
        PostRole.objects.get_or_create(post=post, role_id=role_id)


def _retag(post, names) -> None:
    """Replace the tag set, moving `Tag.post_count` by the difference only."""
    wanted = {tag.pk: tag for tag in resolve_tags(names)}
    current = set(post.tags.values_list("pk", flat=True))

    for removed in current - wanted.keys():
        PostTag.objects.filter(post=post, tag_id=removed).delete()
        Tag.objects.filter(pk=removed).update(post_count=Greatest(F("post_count") - 1, 0))

    for added in wanted.keys() - current:
        PostTag.objects.create(post=post, tag_id=added)
        Tag.objects.filter(pk=added).update(post_count=F("post_count") + 1)


def _reassign_roles(post, roles) -> None:
    """Replace the role set. `usage_count` only moves while the post is live."""
    wanted = {role.pk if isinstance(role, Role) else int(role) for role in roles}
    current = set(post.roles_needed.values_list("pk", flat=True))
    live = post.status == PostStatus.LOOKING

    for removed in current - wanted:
        PostRole.objects.filter(post=post, role_id=removed).delete()
        if live:
            Role.objects.filter(pk=removed).update(
                usage_count=Greatest(F("usage_count") - 1, 0)
            )

    for added in wanted - current:
        PostRole.objects.create(post=post, role_id=added)
        if live:
            Role.objects.filter(pk=added).update(usage_count=F("usage_count") + 1)


# ── Counters (§7) ───────────────────────────────────────────────────────────


def _bump_profile(user_id: int, delta: int) -> None:
    value = F("post_count") + delta if delta >= 0 else Greatest(F("post_count") - 1, 0)
    Profile.objects.filter(user_id=user_id).update(post_count=value)


def _bump_tag_counts(post, delta: int) -> None:
    tag_ids = list(post.tags.values_list("pk", flat=True))
    if not tag_ids:
        return
    value = F("post_count") + delta if delta >= 0 else Greatest(F("post_count") - 1, 0)
    Tag.objects.filter(pk__in=tag_ids).update(post_count=value)


def _bump_role_counts(post, delta: int, *, only_if_live: bool = True) -> None:
    """`Role.usage_count` = live posts requesting the role (PF-6a).

    By default this is skipped for a post that is not `looking`: it is not
    requesting anything, so it was never counted and must not be uncounted —
    which is what `create_post` and `soft_delete_post` need.

    `only_if_live=False` is for `set_status`, which has already decided the
    transition and has already written the new status to the row.
    """
    if only_if_live and post.status != PostStatus.LOOKING:
        return
    role_ids = list(post.roles_needed.values_list("pk", flat=True))
    if not role_ids:
        return
    value = F("usage_count") + delta if delta >= 0 else Greatest(F("usage_count") - 1, 0)
    Role.objects.filter(pk__in=role_ids).update(usage_count=value)


def _refresh_search(post) -> None:
    """Imported lazily: `discovery` imports `posts.models`, and a module-level
    import here would close the loop."""
    from discovery.search import refresh_search_vector

    refresh_search_vector(post)
