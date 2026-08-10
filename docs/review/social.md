# Data-model review — Social seat

**Reviewer:** Social (sparks · comments · saves · notifications) · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock) + ADR-0002, ADR-0003
**Scope:** §2.6 `Comment`, §2.7 `PostSpark`/`CommentSpark`, §2.8 `SavedPost`, §5 `Notification`,
§7 counters, §8 deletion policy.
**Method:** walked each of my four objects through its full lifecycle — create, toggle, soft
delete, hard delete, account anonymise, block — and checked the schema supports every step.

**Headline:** sparks, comments and saves hold up. **Notifications do not.** I found **13 things**;
**4 are schema changes I'd argue must land before lock**, 3 are product decisions only Jeni can
make, the rest are contracts and doc alignment.

The schema-change list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **S4** | Partial `UniqueConstraint` for unread-DM dedup | The documented dedup rule is a read-then-write race with nothing underneath it. Retrofitting means a migration plus a de-dup data cleanup |
| **S5** | `new_follower` dedup rule + matching partial constraint | Third of three triggers has no dedup rule at all |
| **S7** | `CheckConstraint` mapping `kind` → required FK | Free now; a data-cleanup migration later |
| **S9** | `visible_to()` field mapping for `Notification` / `SavedPost` | ADR-0003 fix, not a column — but it is a silent **privacy leak** as written |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a constraint/field before lock. Expensive to retrofit |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but an interface other seats depend on and nobody wrote down |
| ✅ **Checked, fine** | Pressure-tested and correct. Recorded so it doesn't get "improved" |

---

## 1 · Findings

### ✅ S1 — Spark on posts *and* comments without ContentType: the alternative works

§2.7 deliberately avoids a generic relation. I tested the three things that usually break a
two-table design:

- **"Did I spark this?" over a 20-card feed** — one `PostSpark.objects.filter(user=me,
  post_id__in=ids)` → set. No schema support needed.
- **A combined "everything you sparked" screen** — would need a `UNION`. That screen does not
  exist in v1 (`roadmap.md` §1.2 has Saved, not Sparked). Zero cost.
- **Counting / ranking** — plain indexed count on `Index(post)`. `UniqueConstraint(user, post)`
  already covers the `(user, post)` direction, so the separate `Index(post)` is doing real work,
  not duplicating it.

**No change. Do not add a generic `Spark` model.** §2.7's reasoning is correct and I want it on
the record that a feature seat tried to break it and couldn't.

### ✅ S2 — Double-sparking is prevented

`UniqueConstraint(user, target)` on both models, sparks hard-deleted per §8, so toggle is
create/delete. Correct. See **S3** for the counter rule that has to accompany it.

### 🟡 S3 — §7 says *how* to increment a counter, never *when*

§7 rule 1 mandates `F()` expressions in an atomic block. It does not say the increment is
conditional on a row actually being written. `get_or_create` returning `created=False`, or an
`IntegrityError` from a double-tap on mobile, must **not** increment — and the mirror case,
a delete that removed zero rows, must not decrement.

**Requested — §7 rule 5:**

> Only adjust a counter when the underlying row was actually created or actually deleted.
> `created=False` from `get_or_create`, a caught `IntegrityError`, and a delete returning `0`
> are all no-ops for the counter.

Six seats writing toggles from the current text will drift six different ways. This is the
single cheapest fix in this document.

### 🔴 S4 — The DM dedup rule is a race, and nothing in the schema stops it

§5.2 rule 2 — "don't create a `new_message` for a conversation that already has an unread one;
bump the existing row" — is the right product behaviour and the more important of the two rules.
As specified it is `SELECT` then `INSERT` with no constraint underneath.

Two messages arriving within the same few milliseconds, or two Gunicorn workers, both see zero
unread rows and both insert. **The burst is exactly the scenario the rule exists to prevent and
exactly the scenario most likely to trigger the race.**

**Requested — the same pattern §6.1 already uses for `Report`:**

```python
UniqueConstraint(
    fields=["recipient", "conversation"],
    condition=Q(kind="new_message", is_read=False),
    name="uniq_unread_dm_notification_per_conversation",
)
```

Partial unique index in Postgres, so it costs nothing. `NULL` conversations don't collide, so
future group chat is unaffected, and the condition scopes it away from the other two kinds.
Implementation becomes: `.update()` first, create on zero rows, catch `IntegrityError` and
re-`update()` — structurally correct instead of hopefully correct.

**Footgun to record while we're here:** bumping `created_at` works **only** via
`QuerySet.update()`. The field is `auto_now_add` per §0, so a `.save()` path would silently
fail to bump it and the notification would sort to the bottom of the bell. I can live with it —
flagging so it reads as a known choice, not an accident.

### 🔴🟠 S5 — `new_follower` has no dedup rule at all

Rule 1 covers comments. Rule 2 covers messages. The third trigger has nothing.

Follow is one-way, instant, no approval, freely toggleable (§1.4). So follow → unfollow →
follow produces N bell entries from one person. `django-ratelimit` (spec §4.7) lowers the
ceiling; it does not make it one notification.

**Decision needed from Jeni.** My recommendation: **yes, collapse it**, same shape as rule 2 —
don't create a second unread `new_follower` from the same actor to the same recipient, bump
instead. One line of rule, one partial index:

```python
UniqueConstraint(
    fields=["recipient", "actor"],
    condition=Q(kind="new_follower", is_read=False),
    name="uniq_unread_follow_notification_per_actor",
)
```

The follow *edge* belongs to Accounts; the notification is mine, so I need the ruling.

### 🟠 S6 — Rule 1 is a double-submit guard, not a burst guard. Intended?

"Same actor, same post, within 60 seconds" stops a double-click. It does **not** stop one person
leaving five comments over an hour producing five bell entries. That may well be right — five
comments is genuinely five things to read. But it is a structurally different rule from rule 2,
and §5.2 presents the two as a matched pair when they aren't.

**No schema implication either way.** Confirm the asymmetry is deliberate so I don't "fix" it.

### 🔴 S7 — Nothing constrains `kind` against the FK it needs

`Notification` has three nullable FKs and no constraint tying them to `kind`. A `new_follower`
row with a stray `post_id`, or a `new_comment` with `comment = NULL`, is currently legal.

The bell template branches on `kind` and dereferences the matching FK, so a null there is a
blank row or a 500 on the surface that runs on every page load.

§6.1 already does exactly this for `Report` ("exactly one of `reported_user` / `post` /
`comment` is non-null"). Requesting the equivalent here:

| `kind` | Required | Must be null |
|---|---|---|
| `new_comment` | `comment` (and `post`) | `conversation` |
| `new_follower` | — | `post`, `comment`, `conversation` |
| `new_message` | `conversation` | `post`, `comment` |

Free while the table doesn't exist. A data-cleanup migration once it does.

**Note:** `CheckConstraint(recipient != actor)` is already correct and needs no change — `actor`
is nullable and Postgres treats a `NULL` comparison in a check as passing, so system-generated
rows with no actor are fine. Recording it so nobody "hardens" it into rejecting them.

### 🔴 S8 — A notification outlives the thing it points at, and nobody owns the rule

`Notification.post` and `.comment` are `CASCADE`. Posts and comments are **soft**-deleted (§8),
so **CASCADE never fires.**

> A `new_comment` notification survives its comment's deletion. The bell renders an entry
> linking to content that no longer exists — and if it is unread, it inflates the bell count
> permanently for something that will never be there.

Not covered in §5, §7.1 or §8. This needs a decision because I write the bell and Posts & Feed
writes post deletion — two seats, one rule, no shared conversation.

**My recommendation: hard-delete the notification when its post or comment is soft-deleted.**
Notifications are already the one model with a hard-delete + 90-day prune policy (§8) and carry
zero evidential value — the comment row itself survives for moderation, which is the only thing
that matters for a report. The alternatives (render "comment deleted", or join
`comment__deleted_at__isnull=True` into every bell query) both cost more and deliver less.

Whatever is decided belongs in **§7.1's table as a fourth row**, next to the counter rules,
because it is the same class of bug: an invisible object still being counted.

### 🔴 S9 — `visible_to()` has two non-obvious cases and both are on my screens

ADR-0003 §3 specifies `.exclude(<author field>__in=blocked_user_ids(user))`. That is unambiguous
for `Post` and `Comment`. It is **wrong under the naive reading** for the two models ADR-0003
action item 2 assigns to me:

| Model | Field the helper must exclude on | Naive reading gives |
|---|---|---|
| `SavedPost` | `post__author` | `user` — always the viewer, so the Saved screen filters **nothing** and renders blocked authors' posts |
| `Notification` | `actor` | no field called "author" at all |

The `SavedPost` case is a silent privacy leak. QA's `tests/cross/test_block_visibility.py` would
catch it — but only after it ships, and only if the Saved screen is in that table.

**Requested:** write the per-model field mapping explicitly into ADR-0003 §3, covering all six
models listed in its action item 2. No column, but it needs to be in the ADR before the helper
ships, because the helper ships before I write a single view.

### 🟡 S10 — Account anonymisation silently corrupts my counters

§8.1 hard-deletes a departing user's sparks and saves. It says nothing about the counters those
rows fed. Every post that person ever sparked over-reports its `spark_count` permanently.

The weekly reconciliation task (§7 rule 4) papers over it eventually — but "a repair job fixes
it" is not a design, it is a week of visibly wrong numbers on the most-rendered element in the
app, and §7 rule 4 explicitly calls itself a repair for *drift*, not a substitute for a rule.

**Requested — one line in §8.1:** hard-deleting spark / save / follow rows decrements the
corresponding counter in the same transaction, guarded per §7 rule 3.

This sits in Accounts' and Trust & Safety's job, not mine, but it is my counter that goes wrong.

### 🟡 S11 — `Comment.spark_count` is missing from §7's enumeration

§7 opens by listing every denormalised counter. `Comment.spark_count` exists in §2.6 but is not
in that list, and §7.1's soft-delete table has no row for it. Whoever writes the reconciliation
task will scope it from §7 and skip it.

**Requested:** add `Comment.spark_count` to the §7 list, and a §7.1 row — *comment
soft-deleted → its `CommentSpark` rows are not touched; the counter is moot because the comment
is hidden*, matching the existing treatment of a soft-deleted post's sparks.

### 🟡 S12 — Moderation must soft-delete comments through my helper

If a moderator sets `Comment.deleted_at` directly in Django admin, `Post.comment_count` does not
decrement and §7.1 is quietly violated — producing exactly the "12 comments above 11 rendered
ones" bug §7.1 exists to prevent, but only ever in moderated threads, which is the worst place
to have a hard-to-reproduce bug.

I will own a single `soft_delete_comment(comment)` that does both writes atomically.
**Requested:** one line in §11 telling Trust & Safety and admin to call it rather than touching
`deleted_at`.

### 🟠 S13 — ADR-0002's `comment_count` resolution assumes post detail is unpaginated

You already recorded the viewer-dependent counter rule (ADR-0002 §"Counters stay global") and I
agree with it — a viewer-relative count leaks more than it hides, and it would cost 20
aggregates per feed page. **No question here.**

But the resolution rests on one unstated assumption: post detail "renders the length of the
comment list it already fetched," so the heading always matches the comments underneath. **That
only holds if post-detail comments are unpaginated.** Paginate them and page 1 shows "8
comments" above 8 of 40, and the artefact ADR-0002 says is invisible becomes visible on a single
screen.

I will build post detail **unpaginated** for v1. Flagging the ceiling: a 300-comment post
renders 300 rows on a 375px phone. Fine at seed scale, and the fix when it isn't is
"count the total separately", not "make the counter viewer-relative."

---

## 2 · Questions I cannot answer myself

| # | Question | My recommendation |
|---|---|---|
| Q-S1 | Does a **spark** bump `Post.last_activity_at`? §2.3 says spark/comment/edit — but that field drives the anti-ghosting stale job, and a spark from a stranger is not evidence the *author* is still looking. As written, passing sparks keep dead posts artificially fresh and defeat spec §4.8 | **Comments bump it, sparks don't.** Needs Jeni + Trust & Safety |
| Q-S2 | Does a spark on a **comment** bump the parent post's `last_activity_at`? Undefined | **No** |
| Q-S3 | Who owns the weekly counter reconciliation (§7 rule 4) and the 90-day notification prune (§8)? Neither is assigned in §11 | Prune is my model — I'll take it. Reconciliation spans four seats' counters; happy to own it here too |

**Ownership note, not a question:** `last_activity_at` is Trust & Safety's per §11, but the
writes happen inside my comment/spark transactions. I will bump it in the same atomic block.
Recording it so it doesn't read as straying out of my lane.

---

## 3 · Cross-seat notes for the Architect

- **Designer's GAP 13 (`stale_nudge` notification kind) lands in my model.** I support it — the
  anti-ghosting nudge currently has a trigger and no delivery channel. If it's accepted, it
  needs a row in **S7**'s `kind` → FK table (`stale_nudge` requires `post`, forbids
  `comment`/`conversation`) and it is the first kind with a **null `actor`**, which is the case
  §5.1's `CheckConstraint(recipient != actor)` already tolerates. No dedup rule needed — the
  nudge job fires at most once per post per window.
- **Block → notifications is already complete.** ADR-0002 deletes rows where the blocked user is
  `actor`, plus `visible_to()` on the bell. I checked whether actor-based deletion is
  *sufficient*: for all three kinds the actor is always the person whose content is surfaced
  (commenter, follower, sender), so no notification survives blocking while still exposing
  blocked content. **No extra filtering needed** — recording it so nobody adds any.
- **`is_read` is load-bearing, not cosmetic.** Both dedup rules key on `is_read=False`, so
  "mark all as read" is the mechanism that lets the *next* burst create a fresh notification.
  It composes correctly today. Anyone adding a separate "seen" concept later must not repoint
  the dedup rules at it without re-deriving §5.2.

---

## 4 · One product observation, explicitly not a request

Comments are flat and the only `new_comment` recipient is the post author. So when two people go
back and forth in the comments of someone else's post, **neither of them is ever notified** —
only the post owner is. In a product whose thesis is "nobody builds alone," the two people
actually talking to each other are the two flying blind.

Spec §4.6 says exactly three triggers, so **I am building exactly three.** Recorded as a Phase 2
candidate alongside nested threads (§2.6's `parent` note), not as a v1 scope request.

---

## 5 · Summary

| # | Ask | Type | Priority |
|---|---|---|---|
| S4 | Partial `UniqueConstraint` for unread-DM dedup | Schema | 🔴 Blocking |
| S8 | Ruling: notification lifecycle when post/comment is soft-deleted | Decision → §7.1 | 🔴 Blocking |
| S5 | `new_follower` dedup rule + partial constraint | Decision + schema | 🔴 Blocking |
| S9 | `visible_to()` field mapping for `Notification` / `SavedPost` | ADR-0003 fix | 🔴 Leak risk |
| S7 | `CheckConstraint`: `kind` → required FK | Schema | 🟡 Free now, costly later |
| S10 | §8.1 anonymise decrements `spark_count` / `save_count` | Doc rule | 🟡 High |
| S3 | §7 rule 5 — adjust counters only on a real row write | Doc rule | 🟡 High |
| S13 | Confirm post detail renders comments unpaginated | Decision | 🟡 Medium |
| S11 | `Comment.spark_count` named in §7 + reconciliation scope | Doc fix | 🟢 Low |
| S12 | Moderation soft-deletes comments via the Social helper | §11 line | 🟢 Low |
| S6 | Confirm rule 1 / rule 2 asymmetry is deliberate | Decision | 🟢 Low |

S4, S5 and S7 are all **additive constraints on tables that do not exist yet** — trivial in
`posts` 0003 / `notifications` 0001, and each one is a migration plus a data-cleanup step
afterwards.

Nothing in §2.7 or §2.8 needs to change. The spark design is right.
