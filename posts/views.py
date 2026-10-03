"""Posts & Feed views — UI-first wiring from the approved v5 mockups.

Backend logic (ranking, pagination, permissions) lands with the Posts seat;
these views render the Designer templates and query only what each screen needs
to look correct locally.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from posts import services
from posts.forms import PostForm
from posts.models import Post, PostRole, PostSpark, PostStatus, SavedPost
from social.forms import CommentForm
from social.queries import visible_comments


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
    """Screen 6 — post detail, comment thread included.

    The thread comes from `social.queries.visible_comments()` rather than the
    `comments__author__profile` prefetch this view started with. That prefetch
    was a leak: it is not block-filtered, so a blocked person's comments
    rendered in full on a page whose every other element respected ADR-0002.
    The helper also annotates `is_sparked` per viewer and orders oldest-first.

    It is materialised into a list because the fragment renders its length
    twice — the heading and the sticky bar's tally (§7.2) — and a queryset would
    be two more `COUNT`s.
    """
    post = get_object_or_404(_feed_queryset(request.user), slug=slug)
    comments = list(visible_comments(post, request.user))

    return render(
        request,
        "posts/detail.html",
        {
            "post": post,
            "comments": comments,
            "comment_form": CommentForm(),
            # Mirrors social.views: signed in, and not one of the shared demo
            # logins whose password is printed on the landing page (§1.1.1).
            "can_comment": request.user.is_authenticated and not request.user.is_public_demo,
        },
    )


@login_required
def create(request):
    """Screen 7 — publish an idea.

    There are no drafts (§2.3.1): the post is live the moment this succeeds,
    which is why the button says "Publish" and the toast says "Your idea is
    live."

    The public demo accounts get a real 403 (§1.1.1). They may spark and save;
    they may not add content that every later visitor has to read.
    """
    if _refuse_public_demo(request):
        return redirect("posts:feed")

    form = PostForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        post = services.create_post(request.user, **form.field_kwargs, **form.service_kwargs)
        messages.success(request, "Your idea is live.")
        return redirect(post.get_absolute_url())

    return render(request, "posts/create.html", {"form": form, "roles_by_category": _roles_by_category(form)})


@login_required
def edit(request, slug):
    """Edit your own idea. The slug never changes, so neither does the URL.

    Scoped to `author=request.user` in the lookup rather than fetched and then
    checked — there is no ownership `if` to forget (`testing.md` §5.2).
    `all_objects` is deliberately not used: a soft-deleted post is gone, and
    editing one back into existence is not a feature.
    """
    post = get_object_or_404(Post.objects.filter(author=request.user), slug=slug)
    form = PostForm(request.POST or None, instance=post)

    if request.method == "POST" and form.is_valid():
        services.update_post(post, **form.field_kwargs, **form.service_kwargs)
        messages.success(request, "Your idea is updated.")
        return redirect(post.get_absolute_url())

    return render(
        request,
        "posts/create.html",
        {"form": form, "post": post, "roles_by_category": _roles_by_category(form)},
    )


@require_POST
@login_required
def delete(request, slug):
    """Delete your own idea. Soft, because a report may point at it (§8)."""
    post = get_object_or_404(Post.objects.filter(author=request.user), slug=slug)

    services.soft_delete_post(post)
    messages.success(request, "Your idea has been removed.")
    return redirect("posts:feed")


@require_POST
@login_required
def set_status(request, slug):
    """The anti-ghosting control: "yes, still looking" / "team formed" / "closed".

    Also reachable from the stale-post nudge, which is why it is its own
    endpoint rather than only a field on the edit form — answering a nudge
    should be one tap, not a trip through a form.
    """
    post = get_object_or_404(Post.objects.filter(author=request.user), slug=slug)
    status = request.POST.get("status", "")

    if status not in PostStatus.values:
        raise Http404("No such status.")

    services.set_status(post, status)
    messages.success(
        request,
        "Marked as still looking." if status == PostStatus.LOOKING else "Thanks — updated.",
    )
    return redirect(post.get_absolute_url())


def _roles_by_category(form):
    """The role picker, grouped the way the Designer drew it.

    `Role.category` exists to group this one control (`role_category_name_idx`
    is its only index), and a flat list of 41 checkboxes is unusable on a 375px
    screen.

    Groups the form's **bound subwidgets**, not the `Role` rows, so `checked`
    comes from Django rather than from the template comparing a pk against a
    stringified list — which is the version that quietly marks role 1 selected
    because "1" is a substring of "[11]".
    """
    roles = {str(role.pk): role for role in form.fields["roles"].queryset}
    groups: dict[str, list] = {}

    for choice in form["roles"]:
        role = roles.get(str(choice.data["value"]))
        if role is None:  # pragma: no cover - queryset and widget are the same source
            continue
        groups.setdefault(role.get_category_display(), []).append(choice)

    return groups


def _refuse_public_demo(request) -> bool:
    """§1.1.1 — 403 on create-post for the shared demo logins.

    A redirect with a message rather than a bare 403 here, unlike the comment
    endpoint: this is a full page the user navigated to, so an explanation they
    can read beats a browser error page. The permission is still real — there
    is no path through this view for these accounts.
    """
    if not request.user.is_public_demo:
        return False
    messages.info(
        request,
        "The demo account can browse, spark and save — sign up to post your own idea.",
    )
    return True
