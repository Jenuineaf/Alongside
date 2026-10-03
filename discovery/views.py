"""Discovery — Home, search, filters and onboarding.

The phase the roadmap stars: keyword extraction, Postgres full-text search,
ranking and the cascading Home feed are the strongest backend stories in the
project. The logic lives in `feed.py`, `search.py` and `keywords.py`; this
module is the thin layer that turns a request into their arguments.

Two rules run through it:

1. **Public read access is non-negotiable** (`CONTRIBUTING.md` rule 7). Search and the
   filtered feed work signed out. Only Home and onboarding need an account —
   Home because it is personalised to you, onboarding because it edits your
   profile.
2. **Nothing here is ever empty.** Home cascades (`feed.py`), and search tells
   you what it searched for rather than saying "no results".
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from accounts.models import Profile, ProfileInterest
from discovery import search as search_lib
from discovery.feed import DEFAULT_SORT, SORT_OPTIONS, filtered_feed, home_feed
from discovery.forms import FieldForm, InterestsForm, PurposeForm
from posts.models import Commitment, PostStatus, Role, Stage

FEED_PAGE_SIZE = 20
SEARCH_PAGE_SIZE = 20
SUGGESTED_FOLLOW_COUNT = 6
ONBOARDING_STEPS = 3


@require_GET
@login_required
def home(request):
    """Screen 4 — the personalised feed, with the cascade behind it."""
    sections = home_feed(request.user)

    return render(
        request,
        "discovery/home.html",
        {
            "sections": sections,
            "tab_active": "home",
            # Shown once, to somebody who has not finished onboarding: the feed
            # is only as good as what it knows about them, and this is the
            # cheapest moment to say so.
            "prompt_onboarding": request.user.profile.onboarding_completed_at is None,
        },
    )


@require_GET
def explore(request):
    """Screen 5 — the public feed, now with Discovery's filters.

    Signed out and signed in alike. Filters come off the query string so a
    filtered view is a link somebody can send to a friend, which is the whole
    point of keeping this public.

    Renders the Designer's `posts/feed.html` rather than a second explore
    template: it is the same screen, and two templates for one screen is how
    they drift.
    """
    role = request.GET.get("role") or ""
    stage = request.GET.get("stage") or ""
    commitment = request.GET.get("commitment") or ""
    city = request.GET.get("city") or ""
    sort = request.GET.get("sort") or DEFAULT_SORT

    posts = filtered_feed(
        request.user, role=role, stage=stage, commitment=commitment, city=city, sort=sort
    )[:FEED_PAGE_SIZE]

    active_filters = {k: v for k, v in
                      {"role": role, "stage": stage, "commitment": commitment, "city": city}.items()
                      if v}

    return render(
        request,
        "posts/feed.html",
        {
            "posts": posts,
            "tab_active": "explore",
            "roles": Role.objects.filter(is_curated=True, usage_count__gt=0).order_by("name"),
            "stages": Stage.choices,
            "commitments": Commitment.choices,
            "active": active_filters,
            "sort": sort if sort in SORT_OPTIONS else DEFAULT_SORT,
            "has_filters": bool(active_filters),
        },
    )


@require_GET
def search(request):
    """Screen 9 — search results. Posts **and** people (spec §4.3).

    Not comments (§9 Q11): a comment is a reply to something, and a search
    result that is a fragment of a conversation you have no context for is
    noise.

    Both result sets are fetched because the screen shows both with a count on
    each tab — people search is cheap, and a tab that might be empty needs to
    know before it renders.
    """
    query = (request.GET.get("q") or "").strip()
    tab = request.GET.get("tab") or "posts"

    posts = list(search_lib.search_posts(query, request.user)[:SEARCH_PAGE_SIZE])
    people = list(search_lib.search_people(query, request.user)[:SEARCH_PAGE_SIZE])

    return render(
        request,
        "discovery/search.html",
        {
            "query": query,
            "tab": tab if tab in {"posts", "people"} else "posts",
            "posts": posts,
            "people": people,
            "tab_active": "search",
        },
    )


# ── Onboarding ──────────────────────────────────────────────────────────────


@login_required
def onboarding(request, step: int = 1):
    """Screen 3 — three steps, all skippable, all editable later in Settings.

    One view rather than three: the steps share a shell, a progress indicator
    and a skip control, and the only thing that varies is which form is bound.
    Three near-identical views would drift apart.

    Skipping is a real path, not a styled "next": it posts `skip`, writes
    nothing, and moves on. The only thing the last step always writes is
    `onboarding_completed_at`, which records that the flow was *reached the end
    of* — by any path, including skipping everything (§1.2).
    """
    step = max(1, min(int(step), ONBOARDING_STEPS))
    profile = request.user.profile

    if request.method == "POST":
        if "skip" not in request.POST:
            form = _onboarding_form(step, profile, request.POST)
            if form.is_valid():
                _save_onboarding_step(step, profile, form)
            else:
                return _render_onboarding(request, step, profile, form)

        if step >= ONBOARDING_STEPS:
            return _finish_onboarding(request, profile)
        return redirect("discovery:onboarding_step", step=step + 1)

    return _render_onboarding(request, step, profile, _onboarding_form(step, profile))


def _onboarding_form(step: int, profile, data=None):
    if step == 1:
        return PurposeForm(data, instance=profile)
    if step == 2:
        return FieldForm(data, instance=profile)
    return InterestsForm(
        data, initial={"interests": list(profile.interests.values_list("pk", flat=True))}
    )


def _save_onboarding_step(step: int, profile, form) -> None:
    if step in (1, 2):
        form.save()
        if step == 2:
            # `field_tag` and `occupation` are both in the profile's search
            # vector, so people search goes stale the moment this is skipped
            # over without a rebuild.
            _refresh_profile_search(profile)
        return

    # Step 3 — explicit through-model, so the rows are written here.
    chosen = {tag.pk for tag in form.cleaned_data.get("interests") or []}
    existing = set(profile.interests.values_list("pk", flat=True))

    ProfileInterest.objects.filter(profile=profile, tag_id__in=existing - chosen).delete()
    ProfileInterest.objects.bulk_create(
        [ProfileInterest(profile=profile, tag_id=tag_id) for tag_id in chosen - existing]
    )


def _finish_onboarding(request, profile):
    """End of the flow — by any path, including skipping every step."""
    Profile.objects.filter(pk=profile.pk, onboarding_completed_at__isnull=True).update(
        onboarding_completed_at=timezone.now()
    )
    messages.success(request, "You're set up. Here's your feed.")
    return redirect("posts:home")


def _render_onboarding(request, step: int, profile, form):
    return render(
        request,
        "discovery/onboarding.html",
        {
            "step": step,
            "steps": ONBOARDING_STEPS,
            "form": form,
            "suggested": _suggested_follows(request.user, profile) if step == 3 else [],
        },
    )


def _suggested_follows(user, profile):
    """A handful of people worth following, for an account with an empty feed.

    Ranked by follower count within the user's own field, because the cold-start
    problem is "show me somebody relevant", not "show me the most popular person
    on the platform". Falls back to the most-followed overall when the user
    skipped the field step — which is exactly the account that needs the
    suggestions most.

    `visible_to()` applies even here: a blocked person must not be suggested.
    """
    queryset = (
        Profile.objects.visible_to(user)
        .exclude(user=user)
        .exclude(user__anonymised_at__isnull=False)
        .exclude(user__is_public_demo=True)
        .select_related("user")
    )

    if profile.field_tag_id is not None:
        in_field = list(
            queryset.filter(field_tag_id=profile.field_tag_id).order_by("-follower_count")[
                :SUGGESTED_FOLLOW_COUNT
            ]
        )
        if in_field:
            return in_field

    return list(queryset.order_by("-follower_count")[:SUGGESTED_FOLLOW_COUNT])


def _refresh_profile_search(profile) -> None:
    from discovery.search import refresh_profile_search_vector

    refresh_profile_search_vector(profile)
