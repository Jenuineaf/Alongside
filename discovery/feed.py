"""The Home feed, and the cascade that keeps it from ever being empty.

Spec §4.3. Home is the screen a returning user lands on, and a personalised feed
has a cold-start problem by construction: a brand-new account follows nobody and
has no interests, so the honest query returns nothing. An empty Home is how a
portfolio demo dies in ten seconds, so Home **cascades** rather than filters:

| Tier | Query | Label the user sees |
|---|---|---|
| 1 | people you follow **+** your interest tags | "From people and topics you follow" |
| 2 | most-sparked posts in **your field**, last 7 days | "Popular in Design this week" |
| 3 | newest posts overall | "Fresh ideas" |

Each tier only runs if the ones above it did not fill the page, and **every tier
is labelled** (design-system.md §4.5): Home and Feed never use an empty state,
they explain where the posts came from. Without the label, tier 3 looks like a
broken personalised feed rather than a deliberate fallback.

ADR-0004 is what makes tier 2 able to return anything at all. The first draft
had a `Tag.kind` column splitting "field tags" from "topic tags" into disjoint
sets — so "most-sparked posts carrying your field tag" matched nothing, forever,
with no error. One vocabulary, and the tier works.

**QA must assert tier 2 specifically returns rows** (§3). Asserting only that
Home is non-empty passes on tier 3 while hiding exactly the bug ADR-0004 fixed.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from posts.models import Post, PostStatus

# A screenful. Small enough that the cascade is reachable in a demo with 45
# seeded posts, large enough that a well-connected user never sees tier 3.
HOME_PAGE_SIZE = 20

# Tier 2's window. "This week" in the label is a promise the query has to keep.
TIER_2_WINDOW = timedelta(days=7)


class FeedSection:
    """One labelled run of posts on Home.

    A tiny class rather than a dict so the template reads `section.label` and
    cannot silently render an empty string for a typo'd key.
    """

    __slots__ = ("label", "note", "posts", "tier")

    def __init__(self, tier: int, label: str, note: str, posts: list):
        self.tier = tier
        self.label = label
        self.note = note
        self.posts = posts

    def __bool__(self):
        return bool(self.posts)

    def __repr__(self):  # pragma: no cover - debugging only
        return f"<FeedSection tier={self.tier} posts={len(self.posts)}>"


def home_feed(user, limit: int = HOME_PAGE_SIZE) -> list[FeedSection]:
    """The cascade. Returns only the sections that actually have posts.

    Each tier excludes what the tiers above it already showed, so a post never
    appears twice on one screen — the bug that makes a fallback feed look
    broken even when every individual query is right.
    """
    sections: list[FeedSection] = []
    seen: set[int] = set()

    for build in (_tier_1, _tier_2, _tier_3):
        remaining = limit - len(seen)
        if remaining <= 0:
            break
        section = build(user, remaining, seen)
        if section:
            seen.update(post.pk for post in section.posts)
            sections.append(section)

    return sections


def _base(user):
    """Everything every tier needs: visible, live, and annotated for this viewer.

    `visible_to()` then `for_viewer()` — the block filter first, so the
    `EXISTS` annotations are never computed for rows that are about to be
    dropped.
    """
    return (
        Post.objects.visible_to(user)
        .for_viewer(user)
        .filter(status=PostStatus.LOOKING)
        .select_related("author", "author__profile")
        .prefetch_related("tags", "post_roles__role")
    )


def _tier_1(user, limit: int, seen: set[int]) -> FeedSection:
    """People you follow, plus anything carrying a tag you said you're interested in.

    One query with an OR, not two queries unioned: the two sets overlap heavily
    — you follow people who post about what you like — and `distinct()` on one
    query is cheaper and keeps the ordering honest.

    `is_stale` leads the sort here exactly as it does in the main feed: a
    personalised feed full of abandoned posts is worse than a generic one,
    because the user believes these were chosen for them.
    """
    profile = getattr(user, "profile", None)
    if profile is None:
        return FeedSection(1, "", "", [])

    following_ids = list(user.following_edges.values_list("following_id", flat=True))
    interest_ids = list(profile.interests.values_list("pk", flat=True))

    if not following_ids and not interest_ids:
        return FeedSection(1, "", "", [])

    posts = list(
        _base(user)
        .filter(Q(author_id__in=following_ids) | Q(tags__in=interest_ids))
        .exclude(pk__in=seen)
        .exclude(author=user)
        .distinct()
        .order_by("is_stale", "-published_at", "-id")[:limit]
    )

    return FeedSection(
        1,
        "From people and topics you follow",
        "",
        posts,
    )


def _tier_2(user, limit: int, seen: set[int]) -> FeedSection:
    """Most-sparked posts in your field this week.

    The tier ADR-0004 exists for. `Profile.field_tag` is an ordinary `Tag`, so
    it joins against `Post.tags` directly — which is only true because the
    vocabulary was never partitioned.

    Sorted by sparks rather than recency: this tier is answering "what is worth
    reading in your field", and within a 7-day window recency is nearly
    constant anyway.
    """
    profile = getattr(user, "profile", None)
    if profile is None or profile.field_tag_id is None:
        return FeedSection(2, "", "", [])

    since = timezone.now() - TIER_2_WINDOW

    posts = list(
        _base(user)
        .filter(tags__pk=profile.field_tag_id, published_at__gte=since)
        .exclude(pk__in=seen)
        .exclude(author=user)
        .distinct()
        .order_by("-spark_count", "-published_at", "-id")[:limit]
    )

    return FeedSection(
        2,
        f"Popular in {profile.field_tag.name} this week",
        "Because the feed should never be empty.",
        posts,
    )


def _tier_3(user, limit: int, seen: set[int]) -> FeedSection:
    """Newest overall. The floor, and it can always return something.

    Deliberately does **not** exclude the viewer's own posts. By the time
    somebody reaches tier 3 they are new, follow nobody and have no field — and
    a Home screen that hides the one idea they just posted reads as "my post
    didn't save".
    """
    posts = list(
        _base(user)
        .exclude(pk__in=seen)
        .order_by("is_stale", "-published_at", "-id")[:limit]
    )

    return FeedSection(
        3,
        "Fresh ideas",
        "New here — follow a few people and this fills up with your kind of thing.",
        posts,
    )


# ── Filters, for the public Feed (screen 5) ─────────────────────────────────


SORT_OPTIONS = {
    # Each key maps to an ORDER BY that one of the two feed indexes serves
    # column for column (§2.3.2), so the feed stays a forward index scan with no
    # sort node. Adding an option here that no index covers is how the most-hit
    # query in the app quietly becomes a sequential scan.
    "new": ("is_stale", "-published_at", "-id"),
    "sparked": ("is_stale", "-spark_count", "-published_at", "-id"),
}
DEFAULT_SORT = "new"


def filtered_feed(user, *, role=None, stage=None, commitment=None, city=None, sort=None):
    """The public Feed with Discovery's filters applied.

    Every filter is optional and every one of them is exact-match — roles and
    cities are slugs, stage and commitment are choices. That is the whole
    reason roles are curated while tags are free text (ADR-0004): a filter over
    drifting vocabulary silently halves its own result set.

    Tags are deliberately **not** a filter. They are free text, so filtering on
    them would be the exact failure ADR-0004 avoids; searching them is the
    supported path.
    """
    queryset = (
        Post.objects.visible_to(user)
        .for_viewer(user)
        .filter(status=PostStatus.LOOKING)
        .select_related("author", "author__profile")
        .prefetch_related("tags", "post_roles__role")
    )

    if role:
        queryset = queryset.filter(roles_needed__slug=role)
    if stage:
        queryset = queryset.filter(stage=stage)
    if commitment:
        queryset = queryset.filter(commitment=commitment)
    if city:
        queryset = queryset.filter(city_slug=city)

    order = SORT_OPTIONS.get(sort or DEFAULT_SORT, SORT_OPTIONS[DEFAULT_SORT])
    return queryset.distinct().order_by(*order)
