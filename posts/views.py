"""Posts & Feed views — UI-first wiring from the approved v5 mockups.

Backend logic (ranking, pagination, permissions) lands with the Posts seat;
these views render the Designer templates and query only what each screen needs
to look correct locally.
"""

from django.db.models import Exists, OuterRef, Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from posts.models import Post, PostRole, PostSpark, PostStatus, SavedPost


def _feed_queryset(user=None):
    """Posts for public surfaces — newest active ideas, author profile attached.

    `visible_to()` is the block filter every authenticated list owes
    (ADR-0003); it is a no-op returning `self` for anonymous viewers, so the
    public feed stays free of visibility logic.

    `is_sparked` / `is_saved` are annotated rather than queried per card:
    `components/_post_card.html` reads both, and without them every card renders
    as un-sparked and un-saved even on posts you sparked a moment ago. Two
    `EXISTS` subqueries for the whole page, not two queries per card — the N+1
    `testing.md` §5.5 is written to catch.
    """
    queryset = (
        Post.objects.visible_to(user)
        .filter(status=PostStatus.LOOKING)
        .select_related("author", "author__profile")
        .prefetch_related(
            Prefetch("post_roles", queryset=PostRole.objects.select_related("role")),
            "tags",
        )
        .order_by("-spark_count", "-published_at")
    )

    if user is not None and user.is_authenticated:
        queryset = queryset.annotate(
            is_sparked=Exists(PostSpark.objects.filter(user=user, post=OuterRef("pk"))),
            is_saved=Exists(SavedPost.objects.filter(user=user, post=OuterRef("pk"))),
        )
    return queryset


@require_GET
def landing(request):
    """Screen 1 — public landing. Real posts before any sign-up prompt."""
    posts = list(_feed_queryset(request.user)[:2])
    return render(
        request,
        "posts/landing.html",
        {
            "posts": posts,
            "demo_email": "demo@alongside.app",
            "demo_password": "buildtogether",
        },
    )


@require_GET
def feed(request):
    """Screen 5 — public explore feed (all ideas)."""
    posts = _feed_queryset(request.user)[:20]
    return render(
        request,
        "posts/feed.html",
        {
            "posts": posts,
            "tab_active": "explore",
        },
    )


@require_GET
def detail(request, slug):
    """Screen 6 — post detail."""
    post = get_object_or_404(
        _feed_queryset(request.user).prefetch_related("comments__author__profile"),
        slug=slug,
    )
    return render(
        request,
        "posts/detail.html",
        {
            "post": post,
        },
    )


@require_GET
def create(request):
    """Screen 7 — create an idea (form shell; Posts seat wires the POST)."""
    return render(request, "posts/create.html")
