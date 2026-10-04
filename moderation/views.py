"""Reporting — the one thing a user does in this app that a moderator reads.

Three targets, one form, one rule: **you have to be signed in** (Decision H,
Jeni, 3 Oct 2026). Not to make flagging abuse harder, but because "one open
report per person per target" needs a person to key on, and without it the
queue is open to flooding.

Moderation itself is Django admin (§6.1) — there is no custom review UI in v1,
and `status` + `resolution_note` + `reviewed_by` on the report is enough for one
moderator. This module is only the reporting half.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from moderation.forms import ReportForm
from moderation.limits import RATE_REPORT, rate_limit
from moderation.models import Report
from posts.models import Comment, Post

User = get_user_model()


@login_required
@rate_limit(RATE_REPORT)
def report_post(request, slug):
    post = get_object_or_404(Post.objects.visible_to(request.user), slug=slug)
    return _report(request, post=post, target=post, label=post.title, back=post.get_absolute_url())


@login_required
@rate_limit(RATE_REPORT)
def report_comment(request, pk):
    comment = get_object_or_404(
        Comment.objects.visible_to(request.user).select_related("post", "author"), pk=pk
    )
    return _report(
        request,
        comment=comment,
        target=comment,
        label=f"{comment.author.name}'s comment",
        back=f"{comment.post.get_absolute_url()}#comments",
    )


@login_required
@rate_limit(RATE_REPORT)
def report_user(request, username):
    person = get_object_or_404(User, username=username.lower())
    if person.pk == request.user.pk:
        # Reporting yourself is not a thing. 404 rather than a message: there is
        # no URL here worth explaining.
        from django.http import Http404

        raise Http404("You cannot report yourself.")

    return _report(
        request,
        reported_user=person,
        target=person,
        label=person.name,
        back=person.get_absolute_url(),
    )


def _report(request, *, target, label: str, back: str, **target_field):
    """The shared body. `target_field` is exactly one of post/comment/reported_user.

    `target_snapshot` is written here and never again (TS-3, ruled in by Jeni on
    3 Oct 2026). Posts and comments are editable, so without it somebody can
    post something abusive, get reported, and edit it innocuous before anyone
    looks — leaving the moderator ruling on content that no longer exists. It
    cannot be back-filled, which is why it had to be decided before the demo had
    real content.
    """
    form = ReportForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            # The nested `atomic()` is not decoration. Postgres marks the whole
            # transaction unusable after a constraint violation, so catching
            # `IntegrityError` outside a savepoint means every query after this
            # point — including rendering the response — raises
            # `TransactionManagementError`. The savepoint is what makes the
            # exception recoverable rather than fatal.
            with transaction.atomic():
                Report.objects.create(
                    reporter=request.user,
                    reason=form.cleaned_data["reason"],
                    details=form.cleaned_data["details"],
                    target_snapshot=_snapshot(target),
                    **target_field,
                )
        except IntegrityError:
            # `uniq_open_report_per_*` fired: this person already has an open
            # report on this target. That is the normal path, not an error —
            # and it is caught rather than pre-checked, because a check-then-
            # insert is a race that two taps on a phone will lose.
            messages.info(request, "You've already reported this. We're looking at it.")
        else:
            messages.success(request, "Thanks — a moderator will look at this.")
        return redirect(back)

    return render(
        request,
        "moderation/report.html",
        {"form": form, "label": label, "back": back},
    )


def _snapshot(target) -> str:
    """What the reported thing said, at the moment it was reported.

    Title and body for a post, body for a comment, and the public text of a
    profile for a user — a report against a person is usually about their bio or
    their name, and "the account" with no text is as unactionable as a bare
    "other".
    """
    if isinstance(target, Post):
        return f"{target.title}\n\n{target.body}"
    if isinstance(target, Comment):
        return target.body

    profile = getattr(target, "profile", None)
    parts = [target.name, target.username]
    if profile is not None:
        parts += [profile.headline, profile.occupation, profile.bio]
    return "\n".join(part for part in parts if part)
