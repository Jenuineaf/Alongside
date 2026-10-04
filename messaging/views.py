"""Screens 10 and 11 — the conversation list and the chat thread.

Private by definition, so these are login-required reads — one of the few in a
product whose default is public.

**Anyone can message anyone. There is no request gate** (`CLAUDE.md`): the
receiver decides whether to open it. That is a deliberate product call and it
puts weight on the context strip — since nobody has approved anything, "why is
this person messaging me" is the first thing every thread has to answer, which
is what `Conversation.origin_post` is for (GAP 11).

Send-and-refresh rather than WebSockets (Jeni, 3 Oct 2026). Sending posts the
form and re-renders the thread; HTMX swaps it in place so the page does not jump
to the top, and without JavaScript it is a plain form post and a redirect.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.blocking import blocked_user_ids
from messaging import services
from messaging.forms import MessageForm
from messaging.models import Conversation, ConversationParticipant, Message
from moderation.limits import RATE_CONVERSATION, RATE_MESSAGE, rate_limit
from posts.models import Post

User = get_user_model()

THREAD_PAGE_SIZE = 100


@require_GET
@login_required
def list_conversations(request):
    """Screen 10 — every thread, newest activity first.

    Sorted and previewed entirely from denormalised columns on `Conversation`,
    so the list is one query plus the participant join — no aggregate over
    `Message`, which is what those two columns exist to avoid.
    """
    conversations = list(
        Conversation.objects.visible_to(request.user)
        .filter(participants__user=request.user, participants__is_archived=False)
        .select_related("origin_post")
        .prefetch_related(
            Prefetch(
                "participants",
                queryset=ConversationParticipant.objects.select_related("user", "user__profile"),
            )
        )
        .order_by("-last_message_at", "-created_at")
    )

    rows = [_row(conversation, request.user) for conversation in conversations]

    return render(
        request,
        "messaging/list.html",
        {
            "rows": [row for row in rows if row is not None],
            "tab_active": "messages",
        },
    )


@require_GET
@login_required
def thread(request, pk):
    """Screen 11 — one conversation. Opening it marks it read."""
    conversation = _visible_conversation(request, pk)
    other = _other_participant(conversation, request.user)

    services.mark_read(conversation, request.user)

    messages_qs = (
        Message.objects.filter(conversation=conversation)
        .select_related("sender")
        .order_by("created_at")[:THREAD_PAGE_SIZE]
    )

    return render(
        request,
        "messaging/thread.html",
        {
            "conversation": conversation,
            "other": other,
            "messages_list": list(messages_qs),
            "form": MessageForm(),
        },
    )


@require_POST
@login_required
@rate_limit(RATE_MESSAGE)
def send(request, pk):
    """Post a message into a thread you are in."""
    conversation = _visible_conversation(request, pk)
    form = MessageForm(request.POST)

    if form.is_valid():
        services.send_message(conversation, request.user, form.cleaned_data["body"])

    return redirect("messaging:thread", pk=conversation.pk)


@login_required
@rate_limit(RATE_CONVERSATION, method="GET")
def start(request, user_pk):
    """"Message" on a post card or a profile. Opens the thread, creating it once.

    GET, and that is deliberate even though it can write: the button is a link
    from a card, the operation is idempotent by `dyad_key`, and pressing it
    twice gives you the same thread rather than two. Nothing is sent until the
    user types something.

    `?post=<id>` carries the idea it started from. Validated rather than
    trusted — it is a query parameter — and silently dropped if it does not
    resolve, because a missing context strip is better than a 404 on the way
    into a conversation.
    """
    other = get_object_or_404(User, pk=user_pk)

    if other.pk == request.user.pk:
        raise Http404("You cannot message yourself.")
    if other.pk in blocked_user_ids(request.user):
        raise Http404("No such person.")
    if other.anonymised_at is not None:
        raise Http404("That account no longer exists.")
    if request.user.is_public_demo:
        from django.contrib import messages as django_messages

        django_messages.info(
            request,
            "The demo account can browse, spark and save — sign up to message people.",
        )
        return redirect(other.get_absolute_url())

    conversation, _ = services.get_or_create_conversation(
        request.user, other, origin_post=_origin_post(request)
    )
    return redirect("messaging:thread", pk=conversation.pk)


def _origin_post(request):
    post_id = request.GET.get("post")
    if not post_id:
        return None
    return Post.objects.visible_to(request.user).filter(pk=post_id).first()


def _visible_conversation(request, pk) -> Conversation:
    """A thread the viewer is actually in. Anything else is a 404.

    Membership is checked in the lookup rather than after it — there is no
    ownership `if` to forget — and `visible_to()` handles the block case, where
    the thread still exists but must not be reachable (ADR-0002 deletes no
    messages, precisely so unblocking restores the thread for free).
    """
    return get_object_or_404(
        Conversation.objects.visible_to(request.user)
        .filter(participants__user=request.user)
        .select_related("origin_post", "origin_post__author"),
        pk=pk,
    )


def _other_participant(conversation, user):
    for participant in conversation.participants.select_related("user", "user__profile"):
        if participant.user_id != user.pk:
            return participant.user
    return None


def _row(conversation, user):
    """One line in the conversation list, or None if it should not be shown.

    Returns None when the other participant has gone — an anonymised account
    (ADR-0001) leaves its messages in the thread but there is nobody to open a
    conversation *with*, and a list row leading to a tombstone is worse than one
    fewer row.
    """
    participants = list(conversation.participants.all())
    other = next((p.user for p in participants if p.user_id != user.pk), None)
    mine = next((p for p in participants if p.user_id == user.pk), None)

    if other is None or other.anonymised_at is not None:
        return None

    return {
        "conversation": conversation,
        "other": other,
        "unread": mine.unread_count if mine else 0,
    }
