"""Spark, save and comments — the engagement layer.

No models here. `Comment`, `PostSpark`, `CommentSpark` and `SavedPost` all live
in `posts` (they are about posts, and `data-model.md` §2.6–2.8 put them there);
the *behaviour* over them is this seat's. Writes go through
`social/services.py`, which owns the counter rules — nothing in this module
touches a counter or an engagement row directly.

Four rules run through all of it:

1. **Every state change is POST**, login-required.
2. **Everything goes through `visible_to()`** (ADR-0002/0003). The card for a
   blocked author's post is never rendered, but `/s/spark/41/` is guessable, so
   the endpoint has to make the same decision the list did. A 404, never a 403:
   a 403 confirms the row exists.
3. **The server owns the state.** Every toggle re-renders the control it was
   pressed on and HTMX swaps it `outerHTML`, so the count on screen came from
   the database and two open tabs cannot disagree (design-system.md §4.4).
4. **It works without JavaScript.** Each endpoint redirects back to the post
   when the request did not come from HTMX, so the comment form is a plain HTML
   form that happens to be enhanced.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from posts.models import Comment, Post
from social import services
from social.forms import CommentForm
from social.queries import visible_comments


def _visible_post(request, pk: int) -> Post:
    return get_object_or_404(Post.objects.visible_to(request.user).active(), pk=pk)


def _visible_comment(request, pk: int) -> Comment:
    """A comment the viewer may act on — both authors checked.

    Two lookups on purpose. `Comment.visible_to()` filters on the comment's own
    author; it says nothing about the author of the post it hangs under, and a
    block has to hide the whole page either way. Folding both into one clever
    queryset hides which of the two rules is doing the work.
    """
    comment = get_object_or_404(
        Comment.objects.visible_to(request.user).select_related("author", "post"),
        pk=pk,
    )
    _visible_post(request, comment.post_id)
    return comment


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _refuse_public_demo(request):
    """403 for the accounts whose password is printed on the landing page.

    `data-model.md` §1.1.1 is explicit that this is a real permission check and
    that commenting is on the list, with spark and save deliberately off it: the
    demo account may react to things, but it may not add content that every
    later visitor then has to read.

    403 rather than a redirect, because the response is also the contract QA
    asserts as the sixth actor in the permission matrix (`testing.md` §5.2). The
    form is hidden for these accounts too — a hidden button is not a permission,
    but an enforced permission with no explanation is not a product.
    """
    if not request.user.is_public_demo:
        return None
    return HttpResponseForbidden("The demo account can spark and save, but not comment.")


def _comment_section(request, post, form=None):
    """Re-render the whole thread after any change to it.

    One fragment for all three comment endpoints rather than appending a row and
    adjusting a number in place. The heading count, the thread and the sticky
    bar's tally are then the same server-rendered truth, which is the property
    §7.2 asks for — and patching three places in the DOM from three endpoints is
    exactly where off-by-one counts come from.
    """
    comments = list(visible_comments(post, request.user))
    return render(
        request,
        "social/_comment_section_swap.html",
        {
            "post": post,
            "comments": comments,
            "comment_form": form if form is not None else CommentForm(),
            "can_comment": request.user.is_authenticated and not request.user.is_public_demo,
        },
    )


def _back_to_comments(post) -> HttpResponseRedirect:
    """Where a no-JavaScript POST lands: the thread it just changed."""
    return HttpResponseRedirect(f"{post.get_absolute_url()}#comments")


# ── Sparks ──────────────────────────────────────────────────────────────────


@require_POST
@login_required
def spark(request, pk):
    """Toggle a spark on a post and re-render the control."""
    post = _visible_post(request, pk)

    post.is_sparked = services.toggle_post_spark(request.user, post)
    post.refresh_from_db(fields=["spark_count"])

    if not _is_htmx(request):
        return _back_to_comments(post)
    return render(request, "components/_spark.html", {"post": post})


@require_POST
@login_required
def comment_spark(request, pk):
    """Toggle a spark on a comment (spec §4.4 — posts *and* comments)."""
    comment = _visible_comment(request, pk)

    comment.is_sparked = services.toggle_comment_spark(request.user, comment)
    comment.refresh_from_db(fields=["spark_count"])

    if not _is_htmx(request):
        return _back_to_comments(comment.post)
    return render(request, "social/_comment_spark.html", {"comment": comment})


# ── Save ────────────────────────────────────────────────────────────────────


@require_POST
@login_required
def save(request, pk):
    """Toggle a private bookmark and re-render the control.

    This used to return 204 No Content — which HTMX reads as "make no swap" —
    because there was no partial to render back and the alternative was to
    invent the Designer's markup here. `components/_save.html` is now that
    partial, extracted verbatim from `_post_card.html`, so the icon keeps up
    with the click instead of waiting for the next full page render.
    """
    post = _visible_post(request, pk)

    post.is_saved = services.toggle_save(request.user, post)

    if not _is_htmx(request):
        return _back_to_comments(post)
    return render(request, "components/_save.html", {"post": post})


# ── Comments ────────────────────────────────────────────────────────────────


@require_POST
@login_required
def comment_create(request, pk):
    """Add a comment to a post.

    An invalid form comes back as the same fragment with the error attached to
    the field, status 200 — HTMX only swaps 2xx, so answering 400 here would
    discard the one thing the user needs to see (design-system.md §6: swap the
    field, never a full-page error for a partial failure).
    """
    post = _visible_post(request, pk)

    refusal = _refuse_public_demo(request)
    if refusal is not None:
        return refusal

    form = CommentForm(request.POST)
    if not form.is_valid():
        if not _is_htmx(request):
            return _back_to_comments(post)
        return _comment_section(request, post, form=form)

    services.add_comment(request.user, post, form.cleaned_data["body"])
    post.refresh_from_db(fields=["comment_count", "last_activity_at", "is_stale"])

    if not _is_htmx(request):
        return _back_to_comments(post)
    return _comment_section(request, post)


@require_POST
@login_required
def comment_delete(request, pk):
    """Delete your own comment. Soft, because a report may point at it (§8).

    Scoped to `author=request.user` in the lookup itself rather than fetched and
    then checked: there is no ownership `if` to forget, which is the class of bug
    `testing.md` §5.2 is written to catch. Somebody else's comment is a 404.

    Deletable but not editable — a product decision (`data-model.md` §2.6), so
    there is no edit endpoint to go looking for.
    """
    comment = get_object_or_404(
        Comment.objects.select_related("post").filter(author=request.user), pk=pk
    )
    post = comment.post

    services.soft_delete_comment(comment)
    post.refresh_from_db(fields=["comment_count"])

    if not _is_htmx(request):
        return _back_to_comments(post)
    return _comment_section(request, post)
