# ADR-0001: Account deletion anonymises, it does not erase

**Status:** Accepted
**Date:** 31 Jul 2026
**Deciders:** Jeni (CEO) · Architect
**Affects:** Accounts & Profiles · Social · Messaging · Trust & Safety · QA

## Context

`product-spec.md` §4.1 lists "delete account" as a v1 feature but does not say what it does to
the content that account created. This is not a detail — in Alongside a user's rows are woven
through other people's data:

- their **posts** carry other people's comments and sparks
- their **comments** sit inside other people's discussion threads
- their **messages** are half of somebody else's conversation

Whatever we choose becomes a foreign-key policy on effectively every table, and it is the one
decision here that is genuinely irreversible: if we hard-delete a user's rows we cannot get
them back, and the *other* person's thread is damaged permanently.

Forces at play:

- **Honesty to the user.** "Delete my account" should meaningfully remove them.
- **Other people's data.** A conversation is jointly authored. So is a comment thread.
- **Moderation.** `moderation.Report` may reference a user, post or comment. A user who
  harasses someone and then deletes their account must not be able to destroy the evidence.
- **Schema cost.** `CASCADE` everywhere is the cheapest to write and the most destructive.

## Decision

**Anonymise.** Deleting an account deactivates it and scrubs the identifying fields; the
content stays, attributed to a `[deleted]` placeholder. A 30-day grace window runs before the
scrub, during which logging back in restores the account.

Concretely:

| Field | On deletion |
|---|---|
| `User.is_active` | `False` |
| `User.email` | replaced with an unusable non-colliding placeholder |
| `User.username` | retained (it is a foreign key target in URLs and mentions) but rendered as `[deleted]` |
| `User.display_name` | `""` → UI renders `[deleted]` |
| `User.password` | set unusable |
| `Profile.avatar` / `avatar_url` / `bio` / `headline` / `work_done` / links / `occupation` / `city` | cleared |
| `Profile.field_tag`, interests, skills | cleared |
| `Post` / `Comment` / `Message` rows | **kept**, still attributed to the now-anonymous user |
| `Follow` / `Block` / `PostSpark` / `CommentSpark` / `SavedPost` | **hard-deleted** — pure edges, no evidential value |
| `Notification` rows where they are `actor` | hard-deleted |

`User.deletion_requested_at` (nullable datetime) records the start of the grace window; a
scheduled job performs the scrub after 30 days.

## Options Considered

### Option A: Anonymise (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — one well-tested service function |
| Data integrity | High — no dangling rows, no broken threads |
| Privacy story | Good — all personal data gone, content de-identified |
| Reversibility | Grace window makes accidental deletion recoverable |

**Pros:** other people's conversations and comment threads survive intact; moderation evidence
survives; matches what Reddit, GitHub and Instagram do, so it matches user expectation; no
foreign key in the schema has to be `CASCADE` for the sake of deletion.
**Cons:** the row physically remains, so "delete" is a slight overstatement — the Settings copy
has to be honest about it.

### Option B: Hard-delete everything the user ever wrote

| Dimension | Assessment |
|---|---|
| Complexity | Low to write, high to get right |
| Data integrity | Poor — punches holes in third-party threads |
| Privacy story | Strongest |
| Reversibility | None |

**Pros:** cleanest possible privacy answer; nothing to explain.
**Cons:** a comment thread loses replies whose parent vanished; a two-person conversation
becomes a monologue for the person who stayed; a moderation report can be neutralised by the
reported user deleting their account, which is an exploitable abuse path.

### Option C: Delete the account row, reassign content to a permanent `[deleted]` tombstone user

| Dimension | Assessment |
|---|---|
| Complexity | High — every FK must be repointed in one transaction |
| Data integrity | Good |
| Privacy story | Good |
| Reversibility | None |

**Pros:** the user row genuinely disappears.
**Cons:** all deleted users collapse into one identity, so moderation can no longer tell two
bad actors apart; a bulk `UPDATE` across every content table per deletion; no grace window
without extra machinery. Buys very little over Option A for noticeably more work.

## Trade-off Analysis

The real trade is **privacy absolutism vs. third-party data integrity**, and in a product whose
entire purpose is connecting two people, the second wins. A conversation is not solely the
property of the person who wants to leave; the person who stays has a legitimate interest in
their own thread remaining readable.

Option B's privacy advantage over Option A is also smaller than it looks. After anonymisation
nothing personally identifying remains — what survives is an idea post and some comments with
no name attached. The marginal privacy gain from also destroying those is small; the cost to
other users is not.

The abuse path is what settles it. Under Option B, "delete account" becomes a button that
erases evidence of harassment, which makes the moderation queue (`product-spec.md` §4.7)
unreliable by design.

## Consequences

**Easier**
- No FK in the schema needs `CASCADE` in order to make deletion work. `Post.author`,
  `Comment.author` and `Message.sender` stay `CASCADE` for genuine row deletion only, which
  now never happens through the deletion flow.
- Moderation reports keep their subject.
- Accidental deletion is recoverable for 30 days.

**Harder**
- The UI must render `[deleted]` safely everywhere a user is displayed — cards, comments,
  conversation headers, notifications. Every seat that renders a user is affected.
- Settings copy must be honest: "your profile and personal information are permanently
  removed; your posts and comments remain, shown as [deleted]."
- Anonymisation must be idempotent and must run inside one transaction.

**Revisit if**
- A GDPR-style erasure obligation ever applies (out of scope for a portfolio project, but the
  30-day job is where that logic would go).

## Action Items

1. [x] Record in `docs/data-model.md` §8
2. [ ] Add `User.deletion_requested_at` to `accounts` migration 0001
3. [ ] Architect: specify the `anonymise_user()` service signature for the Accounts seat
4. [ ] Accounts seat: build the flow + the honest Settings copy (needs Designer)
5. [ ] Trust & Safety: the 30-day scrub job runs on the same cron path as the stale-post nudge
6. [ ] QA: `testing.md` §10 Q1 is unblocked — test the grace window, idempotency, and that a
   report survives its subject being anonymised
