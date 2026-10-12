# ADR-0002: Block means full mutual invisibility

**Status:** Accepted
**Date:** 31 Jul 2026
**Deciders:** Jeni (CEO) · Architect
**Affects:** every seat. Accounts owns the model; Posts, Discovery, Social and Messaging all
have to honour it.

## Context

`product-spec.md` §4.7 lists "Block a user" with no definition. That is a problem, because
Alongside's second product principle is *anyone can DM anyone, no approval gate*
(`product-spec.md` §2.2). Open messaging is the feature most likely to be abused, which makes
Block the primary safety control rather than a nice-to-have — and its exact semantics change
the query in almost every read path in the app.

Six independent sub-questions were put to the CEO (`data-model.md` §9 Q5): DMs, feed
visibility, reverse feed visibility, existing follows, existing chat history, existing
comments.

**CEO ruling, 31 Jul 2026, verbatim:** *"the person who blocks and the one who gets blocked
cannot get access to anything from each other — not profile, not posts, not chats, nothing."*

That is the strictest of the options offered. It is **symmetric** (it binds the blocker as well
as the blocked) and it is **global** (it is not scoped to the blocker's own posts).

## Decision

A `Block` row is stored one-way — `blocker` → `blocked`, one row — but its **effect is
symmetric**. Two users are *block-related* if a `Block` row exists in **either** direction.

For an **authenticated** viewer V and a block-related user O:

| Surface | Behaviour |
|---|---|
| Profile page | 404 in both directions. Not 403 — 403 confirms the account exists |
| Posts | O's posts are excluded from V's Feed, Home, search results, tag and role pages. Direct URL 404s. Symmetric |
| Comments | O's comments are hidden from V **everywhere**, not only on V's own posts. Symmetric |
| Direct messages | Cannot be sent in either direction |
| Existing conversation | Hidden from both inboxes and inaccessible. **Rows retained, never deleted** — see below |
| Follows | Existing `Follow` rows in **both** directions are hard-deleted at block time |
| Notifications | Existing notifications where O is the `actor` are deleted at block time |
| Existing sparks | Rows retained; they are aggregate signal, not content |
| Saved posts | V's saved posts authored by O are filtered out of the Saved screen, not deleted |
| Search (people) | O never appears in V's people-search results. Symmetric |

**Anonymous visitors are unaffected.** Block is a property of a logged-in viewer's session.
This preserves the non-negotiable public read access (`CONTRIBUTING.md` rule 7) and keeps the
public feed query — the most-hit query in the app — completely free of block logic.

**Unblocking is a full restore** of everything except the rows deleted at block time (follows
and notifications). Those do not come back; the users must re-follow.

### Chat history is hidden, never deleted

**CEO ruling, explicit:** *"existing chat history is hidden from both sides, not deleted. If
they unblock, it comes back. Never destroy the other person's copy."*

Two reasons this is the right call, both worth keeping on the record:

1. **A conversation is jointly owned.** One participant deciding to block should not be able to
   destroy the other participant's copy of a thread they also wrote. This is the same principle
   that drives [ADR-0001](0001-account-deletion-anonymise.md) — leaving does not entitle you to
   delete other people's data.
2. **Moderation evidence survives.** The realistic sequence is *harassment → the victim blocks
   → the victim reports*. If blocking erased the thread, the report would arrive with nothing
   attached and the moderation queue (`product-spec.md` §4.7) would be reliably empty in exactly
   the cases that matter most.

So the product is consistent across all three of soft deletes (`data-model.md` §8), account
deletion, and blocking: **users lose access; the data survives.**

### Block is a soft barrier, not a security control

**This is deliberate and must not be "fixed" later.**

Alongside's feed, posts and profiles are readable **without an account** — `CONTRIBUTING.md` rule 7
calls this non-negotiable, and `product-spec.md` §5.2 makes it a condition of the product
working at all. It follows directly that a blocked person can log out, or open a private
window, and read any public content — including the profile and posts of the person who
blocked them.

That is not a bug and it is not a leak. It is an accepted, understood consequence of public
browsing, and it is the same on every open platform (Reddit, GitHub, X, and Instagram's public
profiles all behave this way).

What Block genuinely provides:

- it removes the other person from your *experience* of the product — feed, search,
  notifications, comments, inbox
- it makes contact impossible: no DMs, no comment replies reaching you, no notifications
- it is a **friction and attention** control, which is what the vast majority of real-world
  blocking is for

What Block does **not** provide, and was never going to:

- it does not make your public content private
- it does not prevent a determined person from reading logged-out
- it is not an access-control boundary and must never be relied on as one

**If someone needs their content genuinely hidden from a specific person, blocking is the
wrong tool** and the product does not currently have the right one — that would be private or
followers-only posts, which are not in v1 scope.

The failure mode this note exists to prevent: a future contributor notices that a blocked user
can see public posts when logged out, reports it as a privacy bug, and "fixes" it by putting
the feed behind a login wall. That would destroy the single most important property of the
product. Public read access wins; block is scoped to the authenticated experience.

## Options Considered

### Option A: Full mutual invisibility (chosen — CEO ruling)

| Dimension | Assessment |
|---|---|
| Complexity | **High** — a block filter is required in nearly every authenticated read path |
| Safety | Strongest available |
| Predictability | Very high — one rule, no exceptions to remember |
| Query cost | Real, but bounded — see [ADR-0003](0003-block-filter-strategy.md) |

**Pros:** a user who blocks someone genuinely stops encountering them, which is what people
actually expect the button to do; nothing to explain in a help page; no partial-visibility
edge cases for the Trust & Safety seat to reason about.
**Cons:** the most expensive option to implement; every seat has to honour it, so it is also
the easiest thing to forget in one view and thereby leak.

### Option B: Asymmetric — blocked user is hidden from the blocker only

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Safety | Weak |
| Predictability | Low |

**Pros:** half the query cost; the blocked party's experience is undisturbed.
**Cons:** the blocked user can still read, spark and comment on the blocker's posts, and still
see their profile. For a harassment case that is close to useless — the blocker still has a
visible, reachable presence to the person they are trying to get away from.

### Option C: Messaging-only block

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Safety | Weak |
| Predictability | High |

**Pros:** trivial — one check in one place, zero feed cost.
**Cons:** addresses only the DM vector. Comment harassment and profile-stalking remain fully
open. Given that comments are explicitly first-class in this product
(`product-spec.md` §2.5), this leaves the second-largest abuse surface unprotected.

## Trade-off Analysis

The trade is **engineering cost vs. safety credibility**, and open DMs are what force the
answer. A product that lets anyone message anyone without an approval gate has taken on an
obligation to make Block real; Options B and C give a control that looks like protection and
mostly isn't, which is worse than a weaker control honestly labelled.

The cost is genuine and worth stating plainly: Option A means roughly a dozen read paths need a
block filter, and any one of them that forgets it is a silent leak. That risk is mitigated
structurally rather than by discipline — see ADR-0003 — because "every seat remembers to add a
filter" is not a design, it is a hope.

### Counters stay global — Architect decision, 31 Jul 2026

Hiding a blocked user's comments makes a viewer-dependent question out of something that was
previously a simple number. If V has blocked O, and O wrote 1 of a post's 12 comments, does
the post show **12** or **11** to V?

**Decision: counters stay global. `comment_count` is 12 for everyone.** Three reasons, in
order of weight:

1. **A viewer-relative count leaks more than it hides.** If the number drops the moment you
   block someone, you have just been told exactly how many comments that person wrote on that
   post — and by checking a few posts you can map their activity precisely. A global count
   reveals nothing. The privacy-motivated option is the less private one, which is
   counter-intuitive enough to be worth writing down.
2. **It defeats the reason the counters exist.** They are denormalised specifically so the feed
   never runs an aggregate (`data-model.md` §7). A viewer-relative count means a
   `COUNT(*) ... WHERE author_id NOT IN (blocked_ids)` per post per request — on a feed page
   rendering 20 cards, that is 20 aggregates to save one number that almost nobody is checking.
3. **Consistency.** `spark_count` is already global and sparks from blocked users are not
   subtracted either. One rule for all counters is easier to hold in your head than a rule with
   an exception.

**The visible artefact and how it is handled:** on the **post detail** page the comment list has
already been fetched, so the heading renders the length of what is actually displayed — the
number always matches the comments underneath it. Only the **feed card** shows the
denormalised global number. So the discrepancy is never visible on a single screen; it exists
only between a card and the page it links to, which no one cross-references. Cheap fix, no
aggregate, no leak.

Recorded here rather than left implicit because "should this count change" will otherwise be
re-asked by every seat that renders a count.

## Consequences

**Easier**
- One rule, stated once, with no per-surface exceptions to memorise.
- The public/anonymous path stays untouched and fast.

**Harder**
- Every authenticated list query gains a filter. Missing it anywhere is a privacy leak, not a
  cosmetic bug.
- Block becomes discoverable by absence: if O blocks V, O's profile disappears for V, which
  V can infer. This matches Instagram and is accepted.
- The Saved screen, the notification bell and the conversation list all need the filter, and
  none of them are obvious places to look for one.
- QA's permission matrix (`testing.md` §5.2) grows an actor and a full row of cases.

**Revisit if**
- Query budgets (`testing.md` §5.4) show the block filter dominating feed latency at seed
  scale. The fallback would be caching the block set harder, not weakening the semantics.

## Action Items

1. [x] Record the semantics in `docs/data-model.md` §1.5
2. [ ] Architect: ship the enforcement helper described in ADR-0003 **before** any feature
   seat writes an authenticated list view
3. [ ] Accounts seat: block/unblock flow, block list in Settings, and the transactional
   follow + notification cleanup at block time
4. [ ] Messaging seat: conversation list and thread both filter on the block set; sending
   checks both directions. **No delete path** — hiding is a filter, so unblocking restores the
   thread for free. There must be no code anywhere that deletes a `Message` on block
5. [ ] Discovery seat: block filter in post search **and** people search
6. [ ] Social seat: comment lists, notification bell, Saved screen
7. [ ] QA: `testing.md` §10 Q5 is unblocked — one test per row of the table above, plus the
   asymmetry test (a one-way row producing two-way effects) and blocks created *after* an
   existing follow and an existing conversation
