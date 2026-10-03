"""Full-text search, and the one function that keeps it fed.

Two halves:

1. `refresh_search_vector(post)` / `refresh_profile_search_vector(profile)` —
   the writers. `data-model.md` §2.3 makes this an **explicit call at the end of
   any transaction that writes post content or its M2M rows**, not a signal: a
   `post_save` receiver fires before the M2M rows exist, so the vector would
   permanently contain no tags and no roles, and `m2m_changed` fires four times
   per save and recomputes each time.
2. `search_posts()` / `search_people()` — the readers. Spec §4.3: search covers
   posts **and people**, and deliberately not comments (§9 Q11).

Everything here uses the **`english_unaccent`** text search configuration, not
plain `english`. That configuration is created in `accounts` 0002 and exists for
one reason (D1): under plain `english`, searching "cafe" does not match "café",
which in a corpus of Indian names and places is not an edge case. Using the
wrong configuration name here fails silently — the query simply returns less.
"""

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import F, Q, Value

from discovery.keywords import keywords_for_post

# Must match the configuration created in `accounts/migrations/0002`.
SEARCH_CONFIG = "english_unaccent"

# Weights, per §2.3 as corrected by PF-4 and D2:
#   A  title
#   B  tags + roles_needed + custom_roles + keywords
#   C  body
#   D  city
#
# The weight letters are what make "an app for canteen food" rank the post
# titled that above the one that mentions canteens in paragraph four.


def refresh_search_vector(post) -> None:
    """Recompute `post.keywords` and `post.search_vector`. Call it last.

    Last, because it reads the M2M rows: call it before `post.tags.set(...)` and
    the vector is built from an empty tag list, which is the silent-failure mode
    §2.3 warns about.

    Written with `.update()` rather than `.save()` so it cannot stamp
    `updated_at` — a system write must not make a post look edited (PF-11) —
    and so it cannot recurse into whatever called it.
    """
    from posts.models import Post

    tag_names = list(post.tags.values_list("name", flat=True))
    role_names = list(post.roles_needed.values_list("name", flat=True))
    custom_roles = list(post.custom_roles or [])

    keywords = keywords_for_post(
        title=post.title,
        body=post.body,
        tags=tag_names,
        roles=role_names,
        custom_roles=custom_roles,
    )

    # Built from Values, not from F() expressions over the M2M, because a
    # SearchVector over a joined multi-valued relation multiplies rows. The
    # names are already in memory above; concatenating them into one weighted
    # term is both correct and one query.
    vector = (
        SearchVector(Value(post.title), weight="A", config=SEARCH_CONFIG)
        + SearchVector(
            Value(" ".join(tag_names + role_names + custom_roles + keywords)),
            weight="B",
            config=SEARCH_CONFIG,
        )
        + SearchVector(Value(post.body), weight="C", config=SEARCH_CONFIG)
        + SearchVector(Value(post.city or ""), weight="D", config=SEARCH_CONFIG)
    )

    Post.all_objects.filter(pk=post.pk).update(keywords=keywords, search_vector=vector)
    post.keywords = keywords


def refresh_profile_search_vector(profile) -> None:
    """The people half of search (spec §4.3).

    Name and headline carry the weight; the bio is background. Skills and
    interests are joined in by name for the same reason post roles are — someone
    searching "Kotlin" should find the Android developer who listed it as a
    skill.
    """
    from accounts.models import Profile

    user = profile.user
    skills = list(profile.skills.values_list("name", flat=True))
    interests = list(profile.interests.values_list("name", flat=True))
    custom_skills = list(profile.custom_skills or [])

    # Contents pinned by §1.2 (D10), and the weights are not negotiable here:
    #   A  display_name + username        B  headline + occupation + skills
    #   C  bio + work_done                D  city
    #
    # Two of the A terms live on `User`, which is why Accounts has to call this
    # when `display_name` or `username` changes — rename yourself without it and
    # you become unfindable under the new name, with no error anywhere.
    vector = (
        SearchVector(
            Value(f"{user.display_name} {user.username}"), weight="A", config=SEARCH_CONFIG
        )
        + SearchVector(
            Value(" ".join([profile.headline, profile.occupation, *skills, *custom_skills])),
            weight="B",
            config=SEARCH_CONFIG,
        )
        + SearchVector(
            Value(" ".join([profile.bio, profile.work_done, *interests])),
            weight="C",
            config=SEARCH_CONFIG,
        )
        + SearchVector(Value(profile.city or ""), weight="D", config=SEARCH_CONFIG)
    )

    Profile.objects.filter(pk=profile.pk).update(search_vector=vector)


# ── Reading ─────────────────────────────────────────────────────────────────


def search_posts(query: str, viewer=None):
    """Ranked post results for a query string. Empty query → empty queryset.

    `SearchQuery(..., search_type="websearch")` rather than the default: it
    accepts what people actually type — quoted phrases, `-excluded` terms — and
    it **never raises on malformed input**. The default `plainto_tsquery` path
    is safe too, but `raw` would turn a stray quote into a 500 on the search box.

    Ranked by `SearchRank` and then by sparks, so two equally relevant ideas are
    ordered by the community's signal. `is_stale` leads nothing here: in a
    deliberate search the user asked for a specific thing, and demoting a stale
    exact match below a fresh vague one is the wrong trade (it is the feed, not
    search, that §2.3.2 demotes).
    """
    from posts.models import Post

    if not query or not query.strip():
        return Post.objects.none()

    search_query = SearchQuery(query, config=SEARCH_CONFIG, search_type="websearch")

    return (
        Post.objects.visible_to(viewer)
        .for_viewer(viewer)
        .filter(
            # The GIN index on `search_vector` serves this. The `keywords`
            # overlap is a second chance for the "Other" free-text roles, which
            # are in the vector at weight B but can also be matched exactly.
            Q(search_vector=search_query)
            | Q(keywords__overlap=[word.casefold() for word in query.split()])
        )
        .annotate(rank=SearchRank(F("search_vector"), search_query))
        .select_related("author", "author__profile")
        .prefetch_related("tags", "post_roles__role")
        .order_by("-rank", "-spark_count", "-published_at", "-id")
    )


def search_people(query: str, viewer=None):
    """Ranked people results. Posts *and people* — spec §4.3.

    Trigram similarity on the name is unioned in by the `ILIKE` branch: a unique
    btree on `username` serves equality, not `'%jen%'`, and people search by
    handle (D4). The trigram indexes on `User.display_name` and `User.username`
    are what make that branch cheap.
    """
    from accounts.models import Profile

    if not query or not query.strip():
        return Profile.objects.none()

    search_query = SearchQuery(query, config=SEARCH_CONFIG, search_type="websearch")
    term = query.strip()

    return (
        Profile.objects.visible_to(viewer)
        .filter(
            Q(search_vector=search_query)
            | Q(user__display_name__icontains=term)
            | Q(user__username__icontains=term)
        )
        .exclude(user__anonymised_at__isnull=False)
        .annotate(rank=SearchRank(F("search_vector"), search_query))
        .select_related("user")
        .order_by("-rank", "-follower_count", "user__username")
    )
