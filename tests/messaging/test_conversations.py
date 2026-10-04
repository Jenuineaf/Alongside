"""Messaging — the dyad key, the unread counter, and the context strip.

Three things carry this feature and each has its own failure mode:

1. **`dyad_key`** stops duplicate threads. Both people pressing Message at the
   same moment is what actually happens when somebody posts an idea and two
   people answer — a read-then-write `get_or_create` loses that race, and the
   unique key is what turns the loser into a recoverable `IntegrityError`.
   M11's zero-padding matters once ids cross a digit boundary, which is roughly
   where the seeded users land.
2. **`unread_count`** is a number, not a dot (decision E), and it must never
   count your own message.
3. **`origin_post`** answers "why is this person messaging me" (GAP 11), the
   question the no-request-gate design makes unavoidable.
"""

import pytest
from django.urls import reverse

from accounts import services as accounts_services
from messaging import services
from messaging.models import Conversation, ConversationParticipant, Message, dyad_key_for
from notifications.models import Notification, NotificationKind
from posts import services as post_services
from posts.models import Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(
        username="dev_krishnan", email="d@example.com", password="pw"
    )


@pytest.fixture
def post(alice):
    return post_services.create_post(
        alice,
        title="An app that moves leftover canteen food",
        body="x",
        stage="idea",
        commitment="casual",
        roles=[Role.objects.filter(is_curated=True).first()],
    )


# ── The dyad key ────────────────────────────────────────────────────────────


def test_the_key_is_the_same_whichever_way_round_it_is_built():
    assert dyad_key_for(9, 10) == dyad_key_for(10, 9)


def test_the_key_is_stable_across_a_digit_boundary():
    """M11 — a string-sorted implementation writes "10:9" for one caller and
    "9:10" for the other, both inserts succeed, and you get the duplicate thread
    the constraint exists to prevent. Passes with ids 1-9; fails at 10."""
    assert dyad_key_for(9, 10) == dyad_key_for(10, 9)
    assert dyad_key_for(2, 100) == dyad_key_for(100, 2)
    assert dyad_key_for(99, 100) == dyad_key_for(100, 99)


def test_a_self_conversation_is_refused():
    with pytest.raises(ValueError):
        dyad_key_for(5, 5)


def test_starting_a_conversation_twice_returns_the_same_one(alice, bob):
    first, created_first = services.get_or_create_conversation(alice, bob)
    second, created_second = services.get_or_create_conversation(bob, alice)

    assert created_first is True
    assert created_second is False
    assert first.pk == second.pk
    assert Conversation.objects.count() == 1


# ── Sending ─────────────────────────────────────────────────────────────────


def test_sending_moves_the_denormalised_columns(alice, bob):
    conversation, _ = services.get_or_create_conversation(alice, bob)

    services.send_message(conversation, alice, "Are you still looking for help?")

    conversation.refresh_from_db()
    assert conversation.last_message_at is not None
    assert conversation.last_message_preview == "Are you still looking for help?"


def test_the_recipient_gets_an_unread_and_the_sender_does_not(alice, bob):
    """Incrementing everybody and zeroing your own leaves you with a badge on a
    conversation you just spoke in, which reads as a bug every time."""
    conversation, _ = services.get_or_create_conversation(alice, bob)

    services.send_message(conversation, alice, "hello")

    assert _unread(conversation, bob) == 1
    assert _unread(conversation, alice) == 0


def test_a_burst_makes_one_notification_but_counts_every_message(alice, bob):
    """Dedup rule 2 (§5.2) — the more important of the two. Ten messages in one
    conversation is one thing to know about, not ten; but the unread COUNT is
    still ten, because that is a different question."""
    conversation, _ = services.get_or_create_conversation(alice, bob)

    for n in range(5):
        services.send_message(conversation, alice, f"message {n}")

    assert Notification.objects.filter(
        recipient=bob, kind=NotificationKind.NEW_MESSAGE
    ).count() == 1
    assert _unread(conversation, bob) == 5


def test_reading_a_thread_clears_both_the_badge_and_the_bell(client, alice, bob):
    conversation, _ = services.get_or_create_conversation(alice, bob)
    services.send_message(conversation, alice, "hello")
    client.force_login(bob)

    client.get(reverse("messaging:thread", args=[conversation.pk]))

    assert _unread(conversation, bob) == 0
    assert Notification.objects.filter(recipient=bob).count() == 0


def test_a_new_message_after_reading_notifies_again(alice, bob):
    """"Mark read" is the dedup reset — otherwise the second burst is silent."""
    conversation, _ = services.get_or_create_conversation(alice, bob)
    services.send_message(conversation, alice, "first")
    services.mark_read(conversation, bob)

    services.send_message(conversation, alice, "second")

    assert Notification.objects.filter(recipient=bob).count() == 1


def test_sending_through_the_view(client, alice, bob):
    conversation, _ = services.get_or_create_conversation(alice, bob)
    client.force_login(alice)

    response = client.post(
        reverse("messaging:send", args=[conversation.pk]), {"body": "Typed in the box."}
    )

    assert response.status_code == 302
    assert Message.objects.get().body == "Typed in the box."


def test_an_empty_message_is_not_sent(client, alice, bob):
    conversation, _ = services.get_or_create_conversation(alice, bob)
    client.force_login(alice)

    client.post(reverse("messaging:send", args=[conversation.pk]), {"body": "   "})

    assert Message.objects.count() == 0


# ── The context strip (GAP 11) ──────────────────────────────────────────────


def test_starting_from_a_post_records_which_idea_it_was(client, bob, post):
    client.force_login(bob)

    client.get(reverse("messaging:start", args=[post.author.pk]), {"post": post.pk})

    assert Conversation.objects.get().origin_post == post


def test_the_thread_shows_what_it_started_about(client, bob, post):
    """"Started about", not "About" — ADR-0005.

    `dyad_key` is unique per pair, so there is one conversation between two
    people forever. If they go on to discuss a second idea, "About: <the first
    one>" is confidently wrong, while "Started about" stays true. One word, and
    it is what makes the field honest.
    """
    client.force_login(bob)
    response = client.get(reverse("messaging:start", args=[post.author.pk]), {"post": post.pk})

    body = client.get(response["Location"]).content.decode()

    assert "Started about" in body
    assert post.title in body


def test_the_strip_survives_the_idea_being_removed(client, bob, post):
    """Posts are SOFT-deleted, so `SET_NULL` never fires and the FK still
    resolves — without the branch the strip links to a 404 (ADR-0005)."""
    client.force_login(bob)
    response = client.get(reverse("messaging:start", args=[post.author.pk]), {"post": post.pk})
    thread_url = response["Location"]

    post_services.soft_delete_post(post)

    body = client.get(thread_url).content.decode()

    assert "since been removed" in body
    assert post.get_absolute_url() not in body


def test_deleting_the_idea_does_not_destroy_the_conversation(client, bob, post):
    """SET_NULL, not CASCADE — the conversation is between two people and
    outlives what started it."""
    client.force_login(bob)
    client.get(reverse("messaging:start", args=[post.author.pk]), {"post": post.pk})
    conversation = Conversation.objects.get()

    post_services.soft_delete_post(post)
    post.delete()  # hard, to prove SET_NULL rather than the soft-delete filter

    conversation.refresh_from_db()
    assert conversation.origin_post is None


def test_a_bogus_post_id_is_dropped_rather_than_404ing(client, bob, alice):
    """It is a query parameter. A missing context strip beats a 404 on the way
    into a conversation."""
    client.force_login(bob)

    response = client.get(reverse("messaging:start", args=[alice.pk]), {"post": "999999"})

    assert response.status_code == 302
    assert Conversation.objects.get().origin_post is None


# ── Who can reach what ──────────────────────────────────────────────────────


def test_messaging_requires_signing_in(client, alice):
    response = client.get(reverse("messaging:start", args=[alice.pk]))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_you_cannot_message_yourself(client, alice):
    client.force_login(alice)

    assert client.get(reverse("messaging:start", args=[alice.pk])).status_code == 404


def test_you_cannot_message_somebody_you_are_block_related_with(client, alice, bob):
    accounts_services.block(alice, bob)
    client.force_login(bob)

    assert client.get(reverse("messaging:start", args=[alice.pk])).status_code == 404


def test_a_blocked_thread_becomes_unreachable_but_is_not_deleted(client, alice, bob):
    """ADR-0002 deletes no messages, precisely so unblocking restores the thread
    for free. Hiding it is a filter, not a delete path."""
    conversation, _ = services.get_or_create_conversation(alice, bob)
    services.send_message(conversation, alice, "hello")
    accounts_services.block(alice, bob)
    client.force_login(bob)

    assert client.get(reverse("messaging:thread", args=[conversation.pk])).status_code == 404
    assert Message.objects.count() == 1

    accounts_services.unblock(alice, bob)
    assert client.get(reverse("messaging:thread", args=[conversation.pk])).status_code == 200


def test_you_cannot_read_a_thread_you_are_not_in(client, alice, bob, django_user_model):
    outsider = django_user_model.objects.create_user(
        username="nosy_parker", email="n@example.com", password="pw"
    )
    conversation, _ = services.get_or_create_conversation(alice, bob)
    client.force_login(outsider)

    assert client.get(reverse("messaging:thread", args=[conversation.pk])).status_code == 404


def test_the_public_demo_account_cannot_message(client, alice, django_user_model):
    """§1.1.1 — browse, spark and save yes; post, comment and DM no."""
    demo = django_user_model.objects.create_user(
        username="demo_account", email="demo@example.com", password="pw", is_public_demo=True
    )
    client.force_login(demo)

    response = client.get(reverse("messaging:start", args=[alice.pk]))

    assert response.status_code == 302
    assert Conversation.objects.count() == 0


# ── The list ────────────────────────────────────────────────────────────────


def test_the_messages_badge_is_block_filtered(client, alice, bob):
    """M17 — ADR-0003's own test enumerates list URLs, and a badge is not one.

    So without an explicit filter the badge counts a conversation with somebody
    the viewer has blocked, on every page, while that test stays green. It is
    the leak the existing coverage is shaped not to catch.
    """
    from notifications.context_processors import unread_alerts

    conversation, _ = services.get_or_create_conversation(alice, bob)
    services.send_message(conversation, alice, "hello")

    request = type("R", (), {"user": bob})()
    assert unread_alerts(request)["unread_messages"] == 1

    accounts_services.block(bob, alice)
    assert unread_alerts(request)["unread_messages"] == 0


def test_the_conversation_list_shows_the_other_person_and_the_preview(client, alice, bob):
    conversation, _ = services.get_or_create_conversation(alice, bob)
    services.send_message(conversation, alice, "The preview text.")
    client.force_login(bob)

    body = client.get(reverse("messaging:list")).content.decode()

    assert alice.name in body
    assert "The preview text." in body


def test_the_list_is_empty_and_says_why(client, alice):
    client.force_login(alice)

    body = client.get(reverse("messaging:list")).content.decode()

    assert "No conversations yet" in body
    assert "Browse ideas" in body


def _unread(conversation, user) -> int:
    return ConversationParticipant.objects.get(conversation=conversation, user=user).unread_count
