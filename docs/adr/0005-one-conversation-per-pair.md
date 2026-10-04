# ADR-0005: One conversation per pair, and `origin_post` means "started about"

**Status:** Accepted
**Date:** 4 Oct 2026
**Deciders:** Jeni (CEO) · Architect
**Affects:** Designer (the chat context strip and its copy) · Builder (conversation creation,
chat thread, conversation list) · QA (seeded threads) · Trust & Safety (first-contact rate limit)

## Context

The core loop of Alongside is *find an idea → message the person who posted it*
(`product-spec.md` §3.4). `CONTRIBUTING.md` rule: **anyone can DM anyone**, with no request gate — the
receiver decides whether to open it. That design choice has a direct consequence on the receiver's
side: **the first question a stranger's DM raises is always "why is this person messaging me?"**

Every chat screen the Designer drew answers it with a context strip above the thread. The schema
had nowhere for that strip to read from: `Conversation` carried `dyad_key`, `last_message_at`,
`last_message_preview` and `created_at`, and **no reference to a `Post`**. The Designer raised it
as GAP 11 and called it the biggest gap in the whole review; the Messaging seat found it
independently (M5) and seconded it, and both noted the same thing — it is cheap now and
unfixable later, because a retrofit has **no possible back-fill**. There is no record anywhere
of which idea a conversation came from once the conversation exists.

Jeni ruled it in on 4 Oct 2026. But the Messaging review found a genuine conflict that the ruling
has to resolve before the column means anything, and it is the real subject of this ADR.

**`dyad_key` and a context strip disagree about what a conversation is.** `dyad_key` is
`"{min_id}:{max_id}"` and it is **unique**, which is what stops two people who both tap "Message"
in the same second from creating two threads — a database constraint instead of a get-or-create
race. The cost of that guarantee is that there is **one conversation per pair of people,
forever**. So:

> Alice messages Bob about idea A. Three weeks later she messages him about idea B. There is no
> second thread — it is the same conversation, and `origin_post` still points at idea A.

A strip reading **"About: idea A"** over a conversation now about idea B is **confidently wrong**,
which is worse than absent.

## Decision

1. **Keep `dyad_key` unique.** One 1:1 conversation per pair of people.
2. **Add `Conversation.origin_post`** — `FK → posts.Post, null=True, on_delete=SET_NULL`,
   `related_name="conversations_started"` — **set once at creation and never updated.**
3. **The field means "what this conversation started about", not "what it is about."** The
   context strip's copy reads **"Started about: …"**. That one word is what makes the column
   truthful in the second-idea case, and it is the whole reason this ADR exists rather than just
   a field in §4.1.
4. The strip must independently check `origin_post.deleted_at` and render "this idea was
   removed", because posts are **soft**-deleted (§8) so `SET_NULL` will essentially never fire.

## Options Considered

### Option A — `origin_post` on `Conversation`, set once, never updated ✅ chosen

| Dimension | Assessment |
|---|---|
| Complexity | **Low** — one nullable FK, written at creation by the existing chokepoint |
| Query cost | **Zero joins** for the strip; it is already `select_related`-able from the thread |
| Correctness | Correct for first contact, **stale** for the rare second-idea case |
| Reversibility | Fully forward-compatible with Option B |

**Pros:** cheapest thing that serves the screen; no change to the duplicate-thread guarantee;
nothing else in the schema moves.
**Cons:** goes stale when one pair discusses two ideas. Mitigated — not hidden — by the copy
("Started about"), which is honest in both cases.

### Option B — `Message.about_post`, a context card rendered inline in the thread

| Dimension | Assessment |
|---|---|
| Complexity | Medium — a column on the **biggest table in the app**, plus a join for the strip |
| Query cost | A join or a second query on the thread page |
| Correctness | **Correct for every case**, including N ideas in one thread |
| Reversibility | n/a — it is the end state |

**Pros:** never stale; matches the Instagram pattern users already know (share a post into a DM
and it renders as a card in place).
**Cons:** pays for the general case before we have evidence anyone hits it. **Rejected for v1,
adopted as the Phase 2 upgrade** — adding a nullable FK to `Message` later is a one-line
migration with no back-fill problem, exactly the reasoning §2.6 uses to leave `Comment.parent`
out of v1.

### Option C — drop `dyad_key` uniqueness so each post gets its own thread

| Dimension | Assessment |
|---|---|
| Complexity | Low to write, **high** to live with |
| Query cost | Similar |
| Correctness | Each thread has one true subject — but the inbox becomes wrong instead |
| Reversibility | **Poor.** Merging fragmented threads later is a data migration with no right answer |

**Pros:** `origin_post` would never be stale.
**Cons:** **rejected.** It gives back the duplicate-thread race the key exists to prevent, and it
fragments one person's conversation history across ideas — so "what did Bob and I say to each
other" stops being answerable, and the unread badge starts counting threads instead of people.
It also multiplies the abuse surface: with no approval gate, the thing worth rate-limiting is
**first contact**, and this option makes first contact cheap and repeatable against the same
person.

## Trade-off Analysis

The decision is **where the context lives**, and that is really a question about which wrongness
is cheaper.

- Option A is wrong **sometimes, visibly, in copy we control**. The failure mode is a strip that
  says "Started about: the canteen food app" above a conversation that has moved on — which, with
  the word *started*, is not even wrong. It is history.
- Option C is wrong **structurally and permanently**: a fragmented inbox cannot be un-fragmented,
  and the duplicate-thread race it reintroduces is the exact bug `dyad_key` was designed for.
- Option B is right and premature. Its cost is a column on the highest-insert table plus a join
  on the hottest messaging query, bought to serve a case we have no evidence of at v1 scale
  (second-idea-same-person). The decisive point is that **A → B is additive**: nothing about
  choosing A today makes B harder tomorrow, and no data is lost in between.

Choosing A is therefore not a compromise between correctness and cost; it is the cheap half of
the correct design, with the expensive half deferred until something asks for it.

## Consequences

**Easier**

- The context strip renders with zero extra queries, on every chat screen, from day one.
- The duplicate-thread guarantee is untouched; re-messaging after an unblock still rejoins the
  original thread with no restore code path (ADR-0002).
- Deleting an idea never destroys a conversation.

**Harder / accepted costs**

- `origin_post` is **not** "the subject of this thread", and anyone reading the field name alone
  will assume it is. That is why the meaning is pinned in three places: this ADR, `data-model.md`
  §4.1, and the comment on the field itself.
- The strip carries two responsibilities the column cannot: the "Started about" wording, and the
  `deleted_at` check. `SET_NULL` is a backstop for a genuine hard delete, **not** the mechanism —
  a soft-deleted post is still reachable through the FK (Django uses `_base_manager` for
  forward-FK access), so without the explicit check the first soft-deleted idea gives every
  reader of that thread a header linking to a 404.
- Profile-initiated DMs have `origin_post = NULL` and every surface must render without a strip.

**To revisit**

- If real usage shows pairs regularly discussing several ideas, implement Option B
  (`Message.about_post`) as the inline card. The trigger is evidence, not taste.

## Action Items

1. [x] `Conversation.origin_post` in `messaging/models.py`, `messaging` 0001 (Architect).
2. [x] Meaning, the two strip obligations and the rejected options recorded in
       `docs/data-model.md` §4.1 and §12.1 (Architect).
3. [ ] **Designer:** change the strip copy from "About: …" to "Started about: …", and draw the
       "this idea was removed" state.
4. [ ] **Builder:** set `origin_post` in the conversation-creation chokepoint — the same helper
       that formats `dyad_key` via `dyad_key_for()` and catches `IntegrityError` — and only
       there, since the field is never updated afterwards. Render the strip with
       `select_related("origin_post")` and branch on `deleted_at`.
5. [ ] **Trust & Safety / Builder:** rate-limit **new conversations created per hour** separately
       from, and tighter than, messages sent in an existing thread (M20). With no approval gate
       the abuse pattern is fifty cold first contacts, not fifty messages.
6. [ ] **QA:** seed at least one pair with a conversation whose `origin_post` is soft-deleted, and
       one profile-initiated DM with `origin_post = NULL`, so both strip states appear on the
       demo site.
