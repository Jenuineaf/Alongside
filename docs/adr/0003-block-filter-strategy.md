# ADR-0003: Block enforcement — one cached id set, one queryset mixin

**Status:** Accepted
**Date:** 31 Jul 2026
**Deciders:** Architect (implementation of [ADR-0002](0002-block-is-mutual-invisibility.md))
**Affects:** every seat that writes an authenticated list view

## Context

[ADR-0002](0002-block-is-mutual-invisibility.md) makes Block symmetric and global. That is the
right product decision and it carries a real engineering risk: **roughly a dozen read paths now
need a block filter, and any single one that forgets it is a privacy leak, not a cosmetic
bug.**

The paths: Feed · Home · post detail · profile page · people search · post search · tag pages ·
role pages · comment lists · notification bell · conversation list · chat thread · Saved.

Six different seats own those, none of them can see each other's chats, and the only shared
memory is `docs/`. "Every seat remembers to add `.exclude(author__in=blocked)`" is not a
design — it is a hope, and it will fail on the view someone writes at 1am in Phase 5.

Constraints:

- Anonymous requests must stay completely free of block logic (`CONTRIBUTING.md` rule 7 — the public
  feed is the most-hit query in the app).
- Blocks are rare per user. A typical user has 0; a heavy user might have 20. The set is small.
- Redis is already in the stack as the cache (`tech-stack.md` §3), so a cache is free to use.
- `testing.md` §5.4 measures query counts and will catch anything that scales per-row.

## Decision

Three pieces, all owned by the Architect and shipped **before** any feature seat writes an
authenticated list view.

### 1. `blocked_user_ids(user) -> frozenset[int]`

One helper in `accounts/blocking.py`. Returns the union of both directions:

```
ids blocked BY user  ∪  ids who have blocked user
```

Computed with a single query against the two indexes `data-model.md` §1.5 already declares
(`Index(blocker)`, `Index(blocked)`). Returns an empty frozenset for anonymous users, before
touching the cache or the database.

### 2. Cached per user, invalidated on write

Cached in Redis under `blocks:v1:<user_id>` with a 1-hour TTL, and **explicitly invalidated for
both users** inside the same transaction that creates or deletes a `Block` row. The TTL is a
backstop against a missed invalidation, not the primary mechanism.

The set is also attached to the request object on first use, so multiple calls within one
request hit neither Redis nor Postgres.

### 3. `VisibleToUserQuerySet` — the filter seats actually call

Every model whose rows are authored by a user gets a queryset method:

```python
Post.objects.visible_to(request.user)
Comment.objects.visible_to(request.user)
Conversation.objects.visible_to(request.user)
```

For an anonymous user this is a no-op returning `self` — zero cost, zero query. For an
authenticated user it applies `.exclude(<author field>__in=blocked_user_ids(user))`.

**Seats call `visible_to()`. They do not call `blocked_user_ids()` directly and they never
hand-write an exclude.** One method name, used identically everywhere.

### 4. The safety net that makes this hold

A QA cross-suite test (`tests/cross/test_block_visibility.py`, added to `testing.md` §5)
enumerates every authenticated list URL from the public-access table and asserts that a blocked
user's content is absent from each. **A new list view that forgets the filter fails a test
owned by someone other than the person who wrote the view** — which is the only mechanism here
that actually works, because it does not depend on anyone remembering anything.

## Options Considered

### Option A: Cached id set + queryset method (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low — one helper, one mixin, one cache key |
| Query cost | One cached lookup per request; zero for anonymous |
| Leak risk | Low, and caught by a cross-cutting test |
| Team familiarity | Plain Django, no magic |

**Pros:** trivial to call correctly; the anonymous fast path is genuinely free; the `NOT IN`
against a handful of integers is negligible next to the joins already in the feed query.
**Cons:** requires cache invalidation, which is one of the two hard problems; a very heavy
blocker (hundreds of blocks) would produce a large `NOT IN`.

### Option B: `NOT EXISTS` subquery / join against the `Block` table per query

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Query cost | A correlated subquery on every feed query |
| Leak risk | Same as A |

**Pros:** no cache, no invalidation, always correct.
**Cons:** pushes work into the hottest query in the app to avoid a cache lookup that costs
under a millisecond. Also harder to read in the ORM, which matters when six seats are copying
the pattern. Trades a cheap, easily-invalidated cache for permanent per-query cost.

### Option C: Middleware that filters globally

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Leak risk | Low but the failure mode is severe |

**Pros:** genuinely impossible to forget.
**Cons:** middleware cannot know which queryset in a view needs filtering, so this becomes
either a manager-level default (which then silently applies to admin and moderation queries,
where blocked content **must** stay visible) or an unpredictable monkey-patch. A default
manager that hides rows from moderators is precisely the bug that makes a moderation queue
untrustworthy. Rejected.

## Trade-off Analysis

The core trade is **where the enforcement lives**: at the call site (A, B) or globally (C).

Global enforcement is seductive because it removes the chance of forgetting, but Alongside has
two viewer classes that must see *different* things — ordinary users (block applies) and
moderators/admin (block must not apply, or the queue is blind). Any mechanism that hides rows
by default will eventually hide them from the one person who needs to see them. That rules out
C regardless of its convenience.

Between A and B, the deciding factor is that the block set is small and changes rarely, which
is the textbook shape for a cache. Paying a correlated subquery on every feed request, forever,
to avoid an invalidation call in the one place blocks are written, is the wrong side of that
trade.

The leak risk that survives is handled by the test in §4, not by the design — and that is the
honest framing. The design makes the correct thing easy; the test makes the incorrect thing
loud.

## Consequences

**Easier**
- Seats write `Post.objects.visible_to(request.user)` and are done thinking about it.
- Anonymous and public paths keep exactly the performance they have today.
- Moderation and admin deliberately use `all_objects` / unfiltered managers and see everything.

**Harder**
- Two cache invalidation points (block create, block delete) that must be inside the
  transaction. Getting this wrong shows up as a block that takes up to an hour to take effect,
  which would be a bad bug and is why the TTL is a backstop rather than the mechanism.
- Every new authenticated list view must be added to the block-visibility test table.

**Revisit if**
- A user accumulates enough blocks that `NOT IN` becomes slow. At that point the set moves to
  a join. Not a v1 concern at ~20 seeded users.

## Action Items

1. [ ] Architect: `accounts/blocking.py` — helper, cache, invalidation hooks
2. [ ] Architect: `visible_to()` on `Post`, `Comment`, `Conversation`, `Notification`,
   `SavedPost`, `Profile` querysets
3. [ ] Architect: document the call convention in `data-model.md` §1.5 so every seat sees it
4. [ ] QA: `tests/cross/test_block_visibility.py`, one row per authenticated list URL
5. [ ] Accounts seat: invalidate both users' cache entries inside the block/unblock transaction
