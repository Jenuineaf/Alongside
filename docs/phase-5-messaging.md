# Phase 5 — Messaging: what shipped

**Seat:** Builder · **Phase:** 5 · **Date:** 4 Oct 2026

Schema and ADR-0005 are the **Architect's** (commits `eda51c2`, `2861146`). Everything below is
the Builder seat's.

**Send-and-refresh, not WebSockets** (Jeni, 3 Oct 2026). The roadmap flags real-time chat as
the one genuine mountain in the project and the first thing to downgrade when time slips — this
is that downgrade, and it keeps the feature while cutting the hard part. Nothing in the write
path would change to put Channels in front of it later: a consumer would push exactly these
rows.

---

## 1. `messaging/services.py` owns every write

| Call | What rides along |
|---|---|
| `get_or_create_conversation(a, b, origin_post=)` | the `dyad_key`, both participant rows |
| `send_message(conversation, sender, body)` | `last_message_at`, `last_message_preview`, the **other** participant's `unread_count`, the sender's `last_read_at`, and the notification |
| `mark_read(conversation, user)` | the badge **and** the bell |
| `soft_delete_message(message)` | the unread counter |

**One conversation per pair, and `dyad_key` is what makes that true.** Both people pressing
Message in the same second is not hypothetical — it is what happens when somebody posts an idea
and two people answer it. A plain `get_or_create` on participant rows is a read-then-write race
with nothing underneath it; the unique key turns the loser into an `IntegrityError` the service
recovers from. Every creation path goes through `messaging.models.dyad_key_for()`, which is the
only place the key is formatted and which also carries the self-DM guard (M12).

**The unread bump excludes the sender.** Incrementing everybody and then zeroing your own is the
version that leaves a badge on a conversation you just spoke in, which reads as a bug every
time.

**`mark_read` clears the bell too.** The badge and the notification are two views of one fact,
and leaving the bell lit for a message the user is reading right now is the kind of small
wrongness that makes a product feel unmaintained.

---

## 2. The context strip — and why the wording matters

`Conversation.origin_post` (GAP 11, ruled in by Jeni 4 Oct 2026) answers the question the
product's own design makes unavoidable: **anyone can DM anyone with no request gate**, so the
receiver's first question is always *why is this person messaging me*.

It reads **"Started about"**, not "About" — ADR-0005. `dyad_key` is unique per pair, so there is
exactly one conversation between two people *forever*. If they go on to discuss a second idea,
"About: <the first one>" is confidently wrong, while "Started about" stays true. One word, and
it is the difference between a field that is honest and one that quietly lies.

It also branches on `origin_post.deleted_at`. Posts are **soft**-deleted, so `SET_NULL` never
fires and the FK still resolves — without the branch the strip links to a 404.

---

## 3. The Messages badge was a leak

`notifications/context_processors.py` now supplies `unread_messages` alongside `unread_alerts`,
and it is **block-filtered** (M17).

Worth stating plainly because it is a good example of coverage-shaped blindness: ADR-0003's own
test enumerates *list URLs* and asserts each one filters blocked users. A badge is not a list
URL. So an unfiltered badge counts a conversation with somebody you have blocked, on every page
in the product, while that test stays green forever.

Both counts return an empty dict for anonymous visitors before any I/O — the public feed is the
most-hit query in the app and `CLAUDE.md` rule 7 makes it non-negotiable.

---

## 4. Rate limiting, and why DMs get two limits

`RATE_MESSAGE` (60/h) governs messages; **`RATE_CONVERSATION` (15/h) governs starting new
ones**, and it is tighter on purpose (M20).

With no request gate, the abuse pattern is not fifty messages in one thread — that is what a
real conversation looks like, and the message limit has to allow it. It is **fifty cold first
contacts**. Those are opposite shapes, so one limit cannot catch the second without strangling
the first.

---

## 5. Tests

`tests/messaging/test_conversations.py` — 25 tests: the dyad key across a digit boundary (M11's
failure mode, which passes with ids 1–9 and breaks at 10), the burst producing one notification
but five unread, reading clearing both badge and bell, the block making a thread unreachable
**without deleting it** so unblocking restores it, the context strip surviving the idea being
removed, and the badge's block filter.

---

## 6. Still open — all behaviour and copy, none of it blocking

The Architect closed every item that was blocking schema. What is left needs a product answer:

| | Question |
|---|---|
| **GAP 12 / M4** | `Conversation.last_message_sender`, so the list can render "You: …". Additive — a nullable FK and one more field in the same transaction — so saying yes later costs a one-line migration and no back-fill. Until then the list shows the preview with no attribution. |
| **M8** | `is_muted` ships with **no defined behaviour** and the model says not to write to it. It is in the approved §4.2 so the Architect kept it; the only plausible meaning is "suppress the `new_message` notification", which is a rule §5.2 does not have. |
| **M9** | Does a new message un-archive a thread? If not, archive quietly becomes mute, and M8 gets harder. |
| **M7** | Is deleting a message user-facing, or retention only? The code assumes retention-only. A user-facing delete needs an affordance and a `[message deleted]` tombstone. |
| **M10** | Can you message an anonymised account? The Messaging seat recommends blocking the send and keeping the thread readable. Today the conversation list drops the row and `start` 404s. |
| **M19** | **The one with a privacy edge.** `[deleted]` still hyperlinks to `/u/<real handle>`, because §8.1 clears every `Profile` field and never touches `User.username`. |
| **`stale_nudge`** | Added on the Trust & Safety seat's written request (TS-2 / Designer GAP 13), **not** on a ruling from Jeni. Recorded that way in `data-model.md`. Cheap to drop while nothing writes to it; needs a one-line confirmation either way. |
