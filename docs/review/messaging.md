# Data-model review — Messaging seat

**Reviewer:** Messaging · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` §4 (`Conversation`, `ConversationParticipant`, `Message`),
plus §1.5 / §5.2 / §7.1 / §8.1 and ADR-0001, ADR-0002, ADR-0003 where they land on my surfaces.
**Method:** walked the three screens I own (conversation list, chat thread, inbox badge) against
the model field by field, then walked the three lifecycle events that cross my area — block,
unblock, account anonymise — and checked each one leaves the thread in a legal state.
**Code state at review:** `messaging/models.py` is an empty docstring, `messaging/migrations/`
is empty, `accounts/blocking.py` does not exist. Nothing in my area is locked.

**Headline:** §4 is broadly right. `dyad_key` is the correct mechanism, `ConversationParticipant`
is the correct shape, and hide-not-delete on block genuinely works — I traced it and unblock
restores for free with no restore code path. I found **20 things**. Five are schema, five are
decisions for Jeni, the rest are contracts nobody has written down.

**Two of my five schema items are seconding the Designer** (`docs/review/designer.md` GAP 11 and
GAP 12) — both land on `Conversation`, which I own the write path for. I agree with both and have
added the implementation consequences their file doesn't cover. **GAP 11 has a genuine conflict
with `dyad_key` that needs resolving before it's added** — see M5.

The schema list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **M1** | `User.anonymised_at` | No field means "anonymised". Six seats told to render `[deleted]` with nothing to branch on. The current workaround already misfires |
| **M5** | `Conversation.origin_post` (seconding Designer GAP 11) | Agreed and irreversible — **but `dyad_key` makes it "first contact context", not "what this thread is about"** |
| **M4** | `Conversation.last_message_sender` (seconding Designer GAP 12) | Agreed. I own the write path; it goes in the same transaction as the other two denormalised fields |
| **M3** | `Message` thread index: partial + `-id` tie-break | Inconsistent with `Comment`'s index, and seeded messages sharing a timestamp make pagination nondeterministic |
| **M2** | `ConversationParticipant.unread_count` | **Conditional on M6.** Only needed if Jeni wants a number rather than a dot |

---

## Severity key

Matching the Designer's file so the Architect can read them together.

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a field/index before lock. Expensive or impossible to retrofit |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but an interface or rule all seats depend on and nobody has written down |
| ⚪ **Relay** | Belongs to another seat. Listed because I'm the one who noticed |

---

## 1 · Schema

### 🔴 M1 — there is no field that means "this account has been anonymised"

§8.1 ends with *"Every seat that renders a user must handle `[deleted]` safely — cards, comments,
conversation headers, notifications."* It then gives those seats nothing to test.

The candidate fields don't work. `is_active=False` is explicitly overloaded in §1.1 — it means
*deactivated*, *banned*, **or** *deleted*. `deletion_requested_at` marks the **start** of the
30-day grace window, not its completion, and during that window the account is fully normal and
must still render its real name.

The Architect has already hit this and worked around it in `accounts/models.py:117`:

```python
if self.deletion_requested_at and not self.is_active:
    return "[deleted]"
```

**That compound proxy misfires on a real sequence.** A user requests deletion, and is then banned
during the grace window — a completely ordinary Trust & Safety action. Now `deletion_requested_at`
is set and `is_active` is `False`, so `name` returns `[deleted]` **while the anonymise job has not
run**: their Profile, bio, links and avatar are all still intact and their profile page still
renders. My conversation list shows `[deleted]` next to a live profile.

```python
anonymised_at = models.DateTimeField(null=True, blank=True, db_index=True)
```

Set by the 30-day job, in the same transaction as the field-clearing. `name` becomes one
unambiguous check, and every other seat gets a single thing to branch on.

**Why now:** this is not really about my screens. Six seats render a user. A two-field proxy that
is wrong in one state will be copied into all six before anyone notices, because it *looks* right.

---

### 🔴 M5 — seconding Designer GAP 11 (`origin_post`), with a conflict to resolve first

I agree with the Designer that this is the one genuinely irreversible finding, and I want it.
The core loop is *find idea → DM the author* (spec §3.4), and the receiver's first question is
always *why is this person messaging me*.

**But `dyad_key` and `origin_post` disagree about what a conversation is,** and the Designer's
file doesn't address it.

`dyad_key` is unique per pair. That means **one conversation per pair of people, forever.** So if
I message you about idea A, and three weeks later message you about idea B, there is no second
thread — it's the same conversation. `origin_post` was set at creation and still points at idea A.
The Designer's context strip would render **"About: idea A"** above a conversation that is now
about idea B. Confidently wrong, which is worse than absent.

Three options:

| | Approach | Assessment |
|---|---|---|
| **a** | Keep `origin_post` on `Conversation`, set once at creation, never updated | Cheap, zero joins, serves the strip. Accepts staleness on the rare second-idea case |
| **b** | Move it to `Message.about_post` — a context card renders inline in the thread | Correct for every case, Instagram-like. Costs a column on the biggest table plus a join for the strip |
| **c** | Drop `dyad_key` uniqueness so each post gets its own thread | **Rejected.** Recreates duplicate-thread races and fragments an inbox across ideas |

**My recommendation: (a), with the label changed.** Second-idea-same-person is rare at v1 scale,
and (b) is the natural Phase 2 upgrade — adding a nullable FK to `Message` later is a one-line
migration, exactly like the `Comment.parent` reasoning in §2.6. What (a) needs is honesty in the
copy: the strip reads **"Started about: …"**, not "About: …". That is a one-word change on the
Designer's side and it makes the field truthful in both cases.

**One correction to the proposed definition.** The Designer specifies `on_delete=SET_NULL` so
deleting the idea doesn't destroy the conversation. Good instinct, wrong mechanism — **posts are
soft-deleted** (§8), so the row survives and `SET_NULL` will essentially never fire. Keep
`SET_NULL` as the backstop for a genuine hard delete, but the strip must independently handle
`origin_post.deleted_at is not None` and render "this idea was removed". Otherwise the first
soft-deleted post produces a conversation header linking to a 404.

---

### 🔴 M4 — seconding Designer GAP 12 (`last_message_sender`)

Agreed, no reservations. The conversation list renders `You: …` and there is no sender on
`Conversation`; joining to `Message` to find it gives back exactly the denormalisation §4.1 exists
to buy.

**What their file doesn't say, and I own:** this is a third denormalised field on `Conversation`
and it must be written in the **same `transaction.atomic()` block** as `last_message_at` and
`last_message_preview`, on every send. Three fields that can drift independently is three chances
to drift. I'd like all three named together in §4.1 as one write, and included in the §7 rule-4
weekly reconciliation job — that job currently covers counters only, and these are the same class
of denormalised value with the same failure mode.

`related_name="+"` and `SET_NULL` as proposed are both fine. Note `SET_NULL` rarely fires here
either, for the same reason as M5 — users are anonymised, not deleted.

---

### 🔴 M3 — the thread index is inconsistent with `Comment`'s, and pagination is nondeterministic

Current: `Index(conversation, -created_at)`.

Two problems, both cheap:

1. **Not partial.** `Comment`'s equivalent is `Index(post, created_at)` partial
   `WHERE deleted_at IS NULL` (§2.6). Messages are soft-deleted too (§8). Same query shape, same
   index treatment — this is just an oversight.
2. **No tie-break.** `created_at` ties are not hypothetical: QA's seed will insert message runs
   inside one transaction, and a realistic demo thread is exactly where they'll cluster. Ties make
   keyset pagination skip or repeat rows, and produce ordering tests that fail one run in twenty.

```
Index(conversation, -created_at, -id) partial WHERE deleted_at IS NULL
```

---

### 🔴 M2 — `ConversationParticipant.unread_count` — **conditional on M6**

Do not add this unless Jeni answers "number" to M6. Recording the shape so the decision is costed:

```python
unread_count = models.PositiveIntegerField(default=0)
# + partial Index(user) WHERE unread_count > 0
```

The partial index mirrors the notification bell in §5.1 — same justification, same shape: it runs
on every page load. Maintained with `F()` per §7 rule 1, guarded against going below zero per
rule 3, and covered by the rule-4 reconciliation job.

If the answer is "dot", **no schema change at all** — see M6.

---

## 2 · Decisions for Jeni

### 🟠 M6 — unread: a dot, or a number?

This is the only decision that changes the schema, so it's the one I need first.

A **dot** ("something new here") is *free* with the model as drafted:
`last_message_at > last_read_at`, zero joins to `Message`, both fields already exist.

A **number** ("3 unread") is not. It's a `COUNT(*)` over `Message` per conversation — precisely the
aggregate §7 denormalises everything else to avoid — and the inbox badge renders on **every page
load**, the same argument that earned the notification bell its partial index in §5.1.

**My recommendation: dot for v1.** Instagram itself shows a dot per row and a number only on the
inbox icon. It's cheaper, it ships sooner, and M2 can be added later without a rewrite, because
nothing else depends on the count existing.

### 🟠 M7 — can a user delete their own message?

§8 says messages are soft-deleted. It never says whether that is a **user-facing feature** or
purely moderation retention. Spec §4.5 lists only "DM/chatbox" and "conversation list + thread".

These are different products: a user-facing delete needs a UI affordance, a "[message deleted]"
tombstone in the thread, and interacts with M16 below. Retention-only needs none of it.

**I'll assume retention-only unless told otherwise** — it matches `Message` having no `updated_at`
and matches comments being deletable-not-editable without a corresponding DM story.

### 🟠 M8 — `is_muted` has no defined behaviour anywhere

The field exists on `ConversationParticipant`. Nothing in the spec, the roadmap, or §5 says what
it does. The only plausible meaning is "suppress the `new_message` notification for this
conversation" — but notifications are the Social seat's, and §5.2 doesn't mention mute.

Either it means that (and §5.2 gains a line, and I pass the flag when I fire the event), or we cut
it. A column nobody writes to is cheaper to remove now than to explain later.

### 🟠 M9 — does a new message un-archive a conversation?

`is_archived` is per-user and correctly placed. Undefined: message arrives on an archived thread —
does it return to the inbox? Instagram: yes. If it doesn't, archive silently becomes mute and M8
gets more confusing. One-line rule, needs to be written down either way.

### 🟠 M10 — can you send to an anonymised account?

The thread stays readable after anonymisation (confirmed below), but nothing says whether the
compose box stays live. Messaging a `[deleted]` account means the message can never be read.

**My recommendation: block sending, keep the thread readable.** Depends on M1 to be checkable at
all — this is a concrete example of why that field matters.

---

## 3 · Contracts — no new columns, but they must be written down

### 🟡 M11 — `dyad_key` is only ordering-independent if `min`/`max` run on integers

§4.1 specifies `"{min_id}:{max_id}"`. `min(9, 10)` is `9`; `min("9", "10")` is `"10"`. A
string-sorted implementation produces `"10:9"` for one caller and `"9:10"` for the other, both
inserts succeed, and you get the duplicate thread the field exists to prevent.

**It passes every test with IDs 1–9.** It starts failing once IDs cross a digit boundary, which at
~20 seeded users is roughly the moment QA's seed data lands.

Pin the format in the field table as zero-padded:

```python
f"{min(a, b):019d}:{max(a, b):019d}"
```

19 digits is `BigAutoField`'s maximum, so this is correct under **both** numeric and lexical sort
and can't be implemented wrongly. Length is 19 + 1 + 19 = **39**, which fits the drafted
`CharField(40)` with one character spare. No column change — just a format that documents itself.

### 🟡 M12 — a nullable unique constraint is opt-out by accident

The nullability is right; it's what buys future group chat without a schema change, and §4.1's
reasoning is sound. The consequence isn't stated: **the constraint protects only rows that
remember to set the key.** A `Conversation()` built anywhere without one creates a silent duplicate
and raises nothing.

So the guarantee is not really the constraint, it's the discipline. That needs one chokepoint,
named in §4.1 so nobody bypasses it: **all 1:1 creation goes through a single `get_or_create`-style
helper that catches `IntegrityError` and re-fetches** (the constraint is what makes the race safe;
the helper is what makes the constraint apply). I own it.

Same helper carries the missing self-DM guard — nothing currently prevents `dyad_key = "5:5"`.
`Follow` and `Block` both have `CheckConstraint(~Q(a=F("b")))` for this; my equivalent can't be a
check constraint because the participants live in another table, so it has to be the helper.

### 🟡 M13 — `last_read_at` is nullable, and the unread comparison silently inverts on NULL

`last_message_at > NULL` evaluates to NULL in SQL, which filters out. So a conversation you have
**never opened** reads as **already read** — exactly backwards, and it lands on the first DM from a
stranger, which is the core loop in spec §3.4.

Every unread query must be written:

```python
Q(last_read_at__isnull=True) | Q(last_message_at__gt=F("last_read_at"))
```

Stated once, in §4.2, next to the field. This is the kind of thing that gets fixed correctly in the
list view and forgotten in the badge.

### 🟡 M14 — sending a message marks the conversation unread to the sender

`last_message_at` bumps on send; the sender's own `last_read_at` doesn't. Their own conversation
immediately shows as unread to them.

One line — set the sender's `last_read_at` in the same transaction as the insert — but it belongs
in the doc beside M4's three-field write, because it's the same transaction and the same
forgettable list.

### 🟡 M15 — `visible_to()` on `Conversation` cannot work as ADR-0003 specifies

ADR-0003 §3 defines the mixin as `.exclude(<author field>__in=blocked_ids)` and lists
`Conversation` among the models receiving it (action item 2). **A `Conversation` has no author
field.** The generic mixin cannot apply, and this will not surface as an error — it will surface as
someone writing something plausible.

The filter has to be:

```python
.exclude(participants__user__in=blocked_user_ids(user))
```

Two things the Architect should pin down when writing it:

- **It must be `.exclude()`, never `.filter(~Q(...))`.** On a multi-valued relation those are not
  equivalent: `exclude()` builds a subquery and drops the conversation if *any* participant is
  blocked (correct); `filter(~Q())` negates per joined row and returns the conversation anyway via
  the *other* participant's row. That is a silent leak, in the single place ADR-0002 cares most
  about.
- **The gate belongs at the `Conversation` level only.** `Message` *does* have a `sender`, so the
  generic mixin would apply to it cleanly — and applying it is wrong. In a 1:1 thread the
  conversation is already hidden, so per-message filtering is redundant, and the only thing it can
  produce is a half-rendered thread with holes in it. Worth an explicit "do not", because adding it
  for symmetry looks like tidiness.

### 🟡 M16 — `last_message_preview` goes stale on soft-delete

§7.1 wrote the "soft-deleted rows don't count" rule for comment counters and stopped there. The
preview is the same class of denormalised value with a worse failure: soft-delete the newest
message and **the inbox keeps rendering its text** — deleted content, still visible, on the list
screen.

§7.1 needs a row: *last message soft-deleted → recompute `last_message_at` / `last_message_preview`
/ `last_message_sender` from the newest surviving message, or render a tombstone.* Which of those
two depends on M7.

### 🟡 M17 — the inbox badge needs the block filter, and no test will catch it

If the badge counts participant rows directly, it reports "1 unread" pointing at a conversation the
block filter has removed from the list — visible, and confusing in exactly the situation where the
user wants to trust the product.

ADR-0003 §4's safety net enumerates *authenticated list URLs*. **The badge is not a list URL**, so
that test will pass while the badge leaks. It needs adding to the block-visibility table explicitly
— same argument as the notification bell, which has the same shape and the same gap.

### 🟡 M18 — the notification contract with Social isn't written anywhere

I fire the event; Social renders it (§5.2 rule 2 is theirs). Nobody has defined the call. I'd like
`notifications.services.notify_new_message(conversation, sender, recipient)` to exist and be named
in §5, so I depend on a function rather than reaching into another seat's model.

One landmine in rule 2 worth flagging to Social while the doc is open: it says to *"bump the
existing row's `created_at`"*. That works via queryset `.update()` but **not** via `.save()`,
because `auto_now_add` only fires on insert — `save()` will silently no-op the bump and the dedup
will look broken while appearing correct.

### 🟡 M19 — `[deleted]` still links to the real handle

§8.1 clears Profile fields and lists them exhaustively. `User.username` is not on that list, and
profile URLs are `/u/<username>`. So an anonymised person in my conversation list renders as
`[deleted]` — hyperlinked to `/u/their_real_handle`, which is the identifying thing anonymisation
was supposed to remove.

Either anonymise rewrites the username, or conversation headers and cards stop linking for
anonymised users. Accounts owns the call; I'm a primary consumer and can't render the header
correctly without it. Depends on M1 either way.

---

## 4 · Relay

### ⚪ M20 — rate limiting should key on new conversations, not just messages sent

Trust & Safety owns this (`django-ratelimit`, no table, §6.1) so there's no schema impact — noting
it because it follows directly from a decision in my area. With no approval gate, the abuse vector
is **first contact with strangers**, not message volume. A limit on messages-per-hour barely
inconveniences someone opening fifty cold threads, which is the actual spam pattern open DMs
attract. The limit that matters is **new conversations created per hour**, separate from and
tighter than messages sent within an existing thread.

---

## 5 · Things I checked that are fine

Recording these so nobody re-reviews them:

- **Hide-not-delete on block genuinely works.** I traced block → unblock. Nothing is deleted, the
  filter is dynamic, so unblock restores the thread with **no restore code path at all**. ADR-0002
  action item 4 is satisfiable exactly as written.
- **Re-messaging after unblock rejoins the original thread.** The `dyad_key` helper finds the
  existing hidden conversation rather than creating a second one, so history reappears in place.
  Correct per ADR-0002, and it falls out of the design rather than needing special handling.
- **Anonymise leaves threads readable.** The `User` row survives (`is_active=False`), so
  `Message.sender` stays a valid FK and a two-person thread never becomes a monologue. The
  mechanism is sound — only the *rendering signal* is broken (M1, M19).
- **`ConversationParticipant` over `user_a`/`user_b`** is the right call, for exactly the reason
  §4.2 gives. Read state is per-user and belongs on a per-user row.
- **`CharField(40)` is correctly sized** — 39 characters worst case with bigint IDs (M11).
- **Nullable `dyad_key` for future group chat** is right, and Postgres NULL-non-collision makes it
  free. The caveat is M12, not the design.
- **No per-message `is_read`.** Correct — one row per participant instead of N per message.
- **The conversation list is 3 queries, not N+1** — `prefetch_related("participants__user__profile")`.
  It over-fetches my own participant row, which is fine.
- **I am *not* asking to denormalise the list sort key.** Honest caveat so nobody re-derives it:
  `Index(user, is_archived)` filters participants, then the query sorts on
  `conversation.last_message_at` — a column on the **joined** table — so this is not the single
  index-ordered scan §4.2 implies. Postgres filters, joins, then sorts. At v1 scale (tens to
  hundreds of conversations per user) that sort is free. Mirroring `last_message_at` onto the
  participant row would remove it, at the cost of a fourth denormalised copy. That's the same call
  the Architect already made for Discovery in §2.3.2 — don't denormalise until a real `EXPLAIN`
  says to. I'd rather revisit with numbers than pay the sync cost on a guess.

---

## 6 · What I need back

1. **M6 first** — dot or number. It's the only decision that changes the schema, and it decides
   whether M2 exists at all.
2. **M1 regardless of anything else.** It's the cheapest item on this list and the only one whose
   absence is already producing wrong behaviour in committed code.
3. **M5 resolved before `origin_post` is added** — the `dyad_key` conflict is real, and adding the
   field without deciding what it means ships a context strip that is confidently wrong. My
   recommendation is option (a) plus the Designer changing "About:" to "Started about:".
4. **M3 and M4** — both small, both cheaper now than as a data migration.
5. **Four rules written into §4** — M11 (key format), M12 (creation chokepoint), M13 (NULL
   semantics), M14 (sender's own read state). No columns, but each one is a silent bug if it lives
   only in my head.
6. **M15 corrected in ADR-0003** before the Architect writes `visible_to()`, since the action item
   as written cannot be implemented.
7. **Decisions on M7–M10**, and **M8 specifically: keep `is_muted` or cut it.**

Everything else in §4 I'd build against as-is. Build order is unchanged either way — HTMX polling
first, Channels only once that's working in front of Jeni.
