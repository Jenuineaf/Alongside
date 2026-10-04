"""Starting conversations and sending messages.

Every write here touches more than one row — a message bumps two denormalised
columns on the conversation and an unread counter on the *other* participant —
so views call these and never write `Message` or `Conversation` directly, the
same contract the other apps hold.

**Send-and-refresh, not WebSockets** (Jeni, 3 Oct 2026). The roadmap flags
real-time chat as the one genuine mountain in the project and the first thing
to downgrade when time slips; this is that downgrade, and it keeps the feature
while killing the hard part. Nothing here would need to change to put Channels
in front of it later — the write path would stay exactly this and a consumer
would push the same rows.
"""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from messaging.models import (
    PREVIEW_LENGTH,
    Conversation,
    ConversationParticipant,
    Message,
    dyad_key_for,
)


@transaction.atomic
def get_or_create_conversation(user_a, user_b, *, origin_post=None) -> tuple[Conversation, bool]:
    """The 1:1 thread between two people, created once.

    `dyad_key` is what makes "once" true. Both people pressing Message at the
    same moment is not hypothetical — it is what happens when somebody posts an
    idea and two people answer it — and a plain `get_or_create` on the
    participant rows is a read-then-write race with nothing underneath it. The
    unique key turns the loser of that race into an `IntegrityError` we can
    recover from, which is the difference between a duplicate thread and a
    retry.

    `origin_post` answers the receiver's first question (GAP 11, ruled in by
    Jeni 4 Oct 2026). Anyone can DM anyone with no request gate, so "why is this
    person messaging me" is the one thing every chat screen has to answer, and
    it is set **only on creation** — a later conversation about something else
    should not rewrite where this one started.
    """
    key = dyad_key_for(user_a.pk, user_b.pk)

    existing = Conversation.objects.filter(dyad_key=key).first()
    if existing is not None:
        return existing, False

    try:
        with transaction.atomic():
            conversation = Conversation.objects.create(dyad_key=key, origin_post=origin_post)
            ConversationParticipant.objects.bulk_create(
                [
                    ConversationParticipant(conversation=conversation, user=user_a),
                    ConversationParticipant(conversation=conversation, user=user_b),
                ]
            )
    except IntegrityError:
        # The other request won. Theirs is the real thread.
        return Conversation.objects.get(dyad_key=key), False

    return conversation, True


@transaction.atomic
def send_message(conversation, sender, body: str) -> Message:
    """Write a message and move everything that depends on it.

    Three denormalised writes ride along, and all three exist so the
    conversation **list** renders with no joins and no aggregates:

    1. `last_message_at` — what the list sorts on.
    2. `last_message_preview` — what it shows.
    3. the other participant's `unread_count` — the badge (decision E: a number,
       not a dot).

    The unread bump deliberately excludes the sender. Incrementing every
    participant and then zeroing your own is the version that leaves you with a
    badge on a conversation you just spoke in, which reads as a bug every time.
    """
    message = Message.objects.create(conversation=conversation, sender=sender, body=body)

    Conversation.objects.filter(pk=conversation.pk).update(
        last_message_at=message.created_at,
        last_message_preview=body[:PREVIEW_LENGTH],
    )
    ConversationParticipant.objects.filter(conversation=conversation).exclude(
        user=sender
    ).update(unread_count=F("unread_count") + 1)

    # The sender's own `last_read_at` moves too (M14). This app tracks unread
    # with a counter rather than a timestamp comparison, so nothing visible
    # depends on it today — but the column exists, and a sender whose
    # `last_read_at` lags behind their own last message is exactly the state
    # that makes a later timestamp-based query report your own thread as unread.
    ConversationParticipant.objects.filter(conversation=conversation, user=sender).update(
        last_read_at=message.created_at
    )

    _notify_recipients(conversation, sender, message)
    return message


@transaction.atomic
def mark_read(conversation, user) -> int:
    """Opening a thread clears its badge. Returns what it cleared.

    Also clears the `new_message` notifications for it: the bell and the
    conversation list are two views of the same fact, and leaving the bell
    showing a message the user is currently reading is the kind of small
    wrongness that makes a product feel unmaintained.
    """
    cleared = ConversationParticipant.objects.filter(
        conversation=conversation, user=user
    ).update(unread_count=0, last_read_at=timezone.now())

    from notifications.models import Notification, NotificationKind

    Notification.objects.filter(
        recipient=user, conversation=conversation, kind=NotificationKind.NEW_MESSAGE
    ).delete()

    return cleared


@transaction.atomic
def soft_delete_message(message) -> bool:
    """Messages are soft-deleted (§8) — a reported one must survive review.

    The preview is **not** recomputed. It is a denormalised convenience, the
    thread itself is the record, and chasing it would mean a query per delete to
    find the new last message. If the deleted message was the preview, the list
    shows a line that is one message stale until the next one arrives — which is
    a smaller wrong than a delete that sometimes costs two extra queries.
    """
    updated = Message.all_objects.filter(pk=message.pk, deleted_at__isnull=True).update(
        deleted_at=timezone.now()
    )
    if not updated:
        return False

    # An unread message that no longer exists must not keep its badge lit.
    ConversationParticipant.objects.filter(conversation_id=message.conversation_id).exclude(
        user_id=message.sender_id
    ).update(unread_count=Greatest(F("unread_count") - 1, 0))

    return True


def _notify_recipients(conversation, sender, message) -> None:
    """One `new_message` notification per other participant.

    Imported lazily, like every other cross-app notification call, so
    `messaging` does not depend on `notifications` at import time.
    """
    from notifications import services as notification_services

    others = (
        ConversationParticipant.objects.filter(conversation=conversation)
        .exclude(user=sender)
        .select_related("user")
    )
    for participant in others:
        notification_services.notify_new_message(participant.user, sender, conversation)
