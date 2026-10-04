"""Profiles, settings, and the follow/block controls.

Three rules run through all of it:

1. **Profiles are public** (`CLAUDE.md` rule 7, spec §5.2). Anonymous visitors
   see them. Sign-in is only needed to follow, block or message.
2. **Block is symmetric and 404s** (ADR-0002). Not 403 — a 403 confirms the
   account exists, which tells a blocked person exactly what they wanted to know.
3. **Every state change is POST**, and every one of them goes through
   `accounts/services.py` rather than touching `Follow` or `Block` here.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from accounts import services
from accounts.blocking import blocked_user_ids
from accounts.forms import FollowNoteForm, ProfileForm
from accounts.models import Block, Follow
from moderation.limits import RATE_FOLLOW, rate_limit
from posts.models import Post

User = get_user_model()

PROFILE_POSTS_LIMIT = 20


def _get_visible_user(request, username: str) -> User:
    """Resolve `/u/<username>/`, honouring the block rule.

    A plain `get_object_or_404(User, ...)` would be a leak: ADR-0002 requires a
    block-related profile to be invisible **in both directions**, and a detail
    view never passes through a queryset, so `visible_to()` does not protect it
    (ACC-7). This is that protection, and it is why every profile-scoped view in
    this module goes through here.

    Anonymised accounts 404 too. There is nothing on the page after a scrub —
    no name, no bio, no avatar — and a tombstone profile is the one place a
    deleted account would still look like an account. Their posts and comments
    survive, rendered as `[deleted]` inline (ADR-0001).
    """
    user = get_object_or_404(User.objects.select_related("profile"), username=username.lower())

    if user.anonymised_at is not None:
        raise Http404("Account no longer exists.")

    if user.pk in blocked_user_ids(request.user):
        raise Http404("No such profile.")

    return user


def _profile_posts(request, author):
    """The author's own ideas, newest first.

    `visible_to()` is applied even though we already know the author is visible:
    the *posts* could be block-related for another reason once co-authoring or
    reposting exists, and using the same call everywhere is the whole point of
    ADR-0003. It is a no-op for anonymous viewers.
    """
    return (
        Post.objects.visible_to(request.user)
        .filter(author=author)
        .select_related("author", "author__profile")
        .order_by("-published_at")[:PROFILE_POSTS_LIMIT]
    )


@require_GET
def profile(request, username):
    """Screen 7 — public, no login wall."""
    person = _get_visible_user(request, username)
    viewer = request.user
    is_self = viewer.is_authenticated and viewer.pk == person.pk

    edge = None
    if viewer.is_authenticated and not is_self:
        edge = Follow.objects.filter(follower=viewer, following=person).first()

    return render(
        request,
        "accounts/profile.html",
        {
            "person": person,
            "profile": person.profile,
            "is_self": is_self,
            "is_following": edge is not None,
            "follow_note_form": FollowNoteForm(initial={"note": edge.note if edge else ""}),
            "posts": _profile_posts(request, person),
            "skills": person.profile.skills.all(),
            "heading": "Profile",
            "back_url": reverse("posts:feed"),
        },
    )


@require_GET
def followers(request, username):
    person = _get_visible_user(request, username)
    return render(
        request,
        "accounts/people_list.html",
        {
            "person": person,
            "heading": "Followers",
            "back_url": person.get_absolute_url(),
            "people": _edge_people(request, person, "follower_edges", "follower"),
        },
    )


@require_GET
def following(request, username):
    person = _get_visible_user(request, username)
    return render(
        request,
        "accounts/people_list.html",
        {
            "person": person,
            "heading": "Following",
            "back_url": person.get_absolute_url(),
            "people": _edge_people(request, person, "following_edges", "following"),
        },
    )


def _edge_people(request, person, related_name, side):
    """Users on one side of `person`'s follow edges, block-filtered for the viewer.

    Filtered against the **viewer's** block set, not `person`'s: this is a list
    of other people, and ADR-0002 says the viewer must not encounter anyone they
    are block-related with, wherever that person turns up.
    """
    hidden = blocked_user_ids(request.user)
    edges = getattr(person, related_name).select_related(f"{side}__profile").order_by("-created_at")
    people = [getattr(edge, side) for edge in edges]
    return [other for other in people if other.pk not in hidden and other.anonymised_at is None]


# ── Editing your own profile ────────────────────────────────────────────────


@login_required
def profile_edit(request):
    """Settings → Edit profile. Always your own; there is no target parameter.

    Taking the user from the session rather than the URL means there is no
    ownership check to forget — the class of bug `testing.md` §5.2 exists to
    catch cannot occur here because the view cannot be pointed at anyone else.
    """
    profile_obj = request.user.profile

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile_obj)
        if form.is_valid():
            form.save(user=request.user)
            messages.success(request, "Profile saved.")
            return redirect(request.user.get_absolute_url())
    else:
        form = ProfileForm(
            instance=profile_obj, initial={"display_name": request.user.display_name}
        )

    return render(
        request,
        "accounts/profile_edit.html",
        {"form": form, "heading": "Edit profile", "back_url": reverse("accounts:settings")},
    )


# ── Follow ──────────────────────────────────────────────────────────────────


@require_POST
@login_required
@rate_limit(RATE_FOLLOW)
def follow(request, username):
    """One tap, instant, no approval.

    The Designer's flow (mockup §7, open question 2): the follow lands
    immediately and the optional note is offered afterwards, rather than asking
    for a note first and putting a text box in front of a one-tap action.
    """
    person = _get_visible_user(request, username)

    if person.pk == request.user.pk:
        raise Http404("You cannot follow yourself.")
    if _refuse_public_demo(request):
        return redirect(person.get_absolute_url())

    _, created = services.follow(request.user, person)
    if created:
        messages.success(request, f"You're following {person.name}. They've been notified.")

    return redirect(_safe_next(request, person.get_absolute_url()))


@require_POST
@login_required
def unfollow(request, username):
    person = _get_visible_user(request, username)
    services.unfollow(request.user, person)
    return redirect(person.get_absolute_url())


@require_POST
@login_required
def follow_note(request, username):
    """Attach the optional note to an existing follow (spec §4.4).

    Refuses to create the follow as a side effect: if the edge is gone — they
    unfollowed in another tab, or a block removed it — the honest answer is to
    do nothing rather than silently re-follow someone on the strength of a note.
    """
    person = _get_visible_user(request, username)
    form = FollowNoteForm(request.POST)

    if form.is_valid():
        updated = Follow.objects.filter(follower=request.user, following=person).update(
            note=form.cleaned_data["note"]
        )
        if updated:
            messages.success(request, "Note sent.")

    return redirect(person.get_absolute_url())


# ── Block ───────────────────────────────────────────────────────────────────


@require_POST
@login_required
def block(request, username):
    """Full mutual invisibility, effective immediately (ADR-0002).

    Redirects to the feed rather than back to the profile — the profile is a
    404 for this viewer from the moment the block lands, so returning there
    would present an error page as the confirmation of a successful action.
    """
    person = _get_visible_user(request, username)

    if person.pk == request.user.pk:
        raise Http404("You cannot block yourself.")
    if _refuse_public_demo(request):
        return redirect(person.get_absolute_url())

    services.block(request.user, person)
    messages.success(
        request,
        "Blocked. You won't see each other's profiles, posts, comments or messages.",
    )
    return redirect(reverse("posts:feed"))


@require_POST
@login_required
def unblock(request, username):
    """Undo a block.

    Deliberately does **not** go through `_get_visible_user`: while the block
    exists the other person is a 404 to this viewer, so resolving them the
    normal way would make unblocking impossible. This is the same exception the
    block list itself needs (ACC-8) and the only place in the app that looks a
    user up without the visibility filter.
    """
    person = get_object_or_404(User, username=username.lower())
    services.unblock(request.user, person)
    messages.success(request, f"Unblocked {person.name}.")
    return redirect(reverse("accounts:blocked"))


@login_required
@require_GET
def blocked_list(request):
    """Settings → Blocked people.

    **The one authenticated surface where `visible_to()` must not apply**
    (ACC-8, now recorded in `data-model.md` §1.5). Filtering this list would
    hide exactly the people it exists to show, and leave no way to unblock
    anyone.
    """
    blocks = (
        Block.objects.filter(blocker=request.user)
        .select_related("blocked", "blocked__profile")
        .order_by("-created_at")
    )
    return render(
        request,
        "accounts/blocked_list.html",
        {"blocks": blocks, "heading": "Blocked people", "back_url": reverse("accounts:settings")},
    )


# ── Settings and deletion ───────────────────────────────────────────────────


@login_required
@require_GET
def settings(request):
    """Screen 13."""
    profile_obj = request.user.profile
    return render(
        request,
        "accounts/settings.html",
        {
            "profile": profile_obj,
            "interests": profile_obj.interests.all(),
            "blocked_count": Block.objects.filter(blocker=request.user).count(),
            "heading": "Settings",
            "back_url": request.user.get_absolute_url(),
        },
    )


@login_required
def delete_account(request):
    """Start the 30-day grace window (ADR-0001).

    GET renders the confirmation and states plainly what survives; POST starts
    the clock. Never a GET side effect — `testing.md` §6 requires every
    irreversible action to be POST-and-confirmed, and this is the most
    irreversible one in the product.

    The account is **not** deactivated here. ADR-0001 makes logging back in the
    way to cancel, and Django's `ModelBackend` refuses to authenticate an
    inactive user — deactivating now would make the grace window unreachable and
    the deletion effectively immediate.
    """
    if request.method == "POST":
        services.request_deletion(request.user)
        messages.success(
            request,
            "Your account is scheduled for deletion in 30 days. Log in any time before "
            "then to cancel it.",
        )
        return redirect(reverse("accounts:settings"))

    return render(
        request,
        "accounts/delete_account.html",
        {"heading": "Delete account", "back_url": reverse("accounts:settings")},
    )


@require_POST
@login_required
def cancel_deletion(request):
    services.cancel_deletion(request.user)
    messages.success(request, "Your account is no longer scheduled for deletion.")
    return redirect(reverse("accounts:settings"))


# ── Shared guard ────────────────────────────────────────────────────────────


def _safe_next(request, fallback: str) -> str:
    """Where to land after a follow. Defaults to the profile.

    Onboarding needs it: following somebody from the suggestions there would
    otherwise dump the user on that person's profile with the flow abandoned at
    step 3 — the one step that writes `onboarding_completed_at`.

    `url_has_allowed_host_and_scheme` is not optional. A bare
    `redirect(request.POST["next"])` is an open redirect: anyone could post a
    form at this endpoint with `next=https://example.com` and bounce a signed-in
    user off-site from a URL that looks like ours.
    """
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return fallback


def _refuse_public_demo(request) -> bool:
    """The published-credentials accounts cannot change the social graph.

    `data-model.md` §1.1.1 restricts posting, commenting and DMs. Block belongs
    on that list and was missing (ACC-9): the demo login is shared by every
    visitor, a block is global and permanent in effect, and it hard-deletes
    follows that unblocking never restores — so one visitor can quietly degrade
    the seeded demo graph for everyone after them.

    Follow is included for the same reason at lower stakes: it dirties seeded
    `follower_count`s that `--reset` does not repair.

    Enforced here at the request layer and **never** in `Model.save()` or a
    signal — the seed command has to be able to build the demo account's state
    (`testing.md` §7.5).
    """
    if not request.user.is_public_demo:
        return False
    messages.info(
        request,
        "The demo account can browse, spark and save — sign up to follow people.",
    )
    return True
