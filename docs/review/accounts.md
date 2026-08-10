# Data-model review — Accounts & Profiles seat

**Reviewer:** Accounts & Profiles · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock) §1.1–§1.6, §7, §8, §9, §10
· ADR-0001, ADR-0002, ADR-0003 · `product-spec.md` §3.1, §4.1, §4.4, §4.7
**Also reviewed as shipped code:** `accounts/models.py`, `accounts/validators.py`,
`accounts/migrations/0001_initial.py`, `config/settings/base.py`

**Headline:** the model holds up. My area is well served and ADR-0001/0002/0003 are the right
calls. I found **14 things**: **four schema changes**, **five undocumented contracts that will
produce silent bugs**, **three product decisions only Jeni can make**, and two nits.

Everything in `accounts/` is still untracked, so even migration 0001 is free to change today.
That is why ACC-1 is worth raising now and not in September.

The schema-change list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **ACC-1** | `User.anonymised_at` | Column on `User` — the one table this project reorganised itself to avoid altering later |
| **ACC-2** | `Notification.follow` FK | The follow note is currently unrenderable. Ships broken without it |
| **ACC-3** | `ProfileSkill.role` → `PROTECT` | Unspecified in §1.3. Free now, a data-loss bug later |
| **ACC-4** | Drop 4 redundant Meta indexes | Free now, a migration later |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a field or a change before lock. Expensive or impossible to retrofit |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but an interface other seats depend on and nobody has written down |
| ⚪ **Mine** | My own debt. Listed for visibility, not to create Architect work |

---

## 1 · Findings

### 🔴 ACC-1 — `User` cannot tell "scrubbed" from "banned mid-grace-window"

`anonymised_at = models.DateTimeField(null=True, blank=True, db_index=True)`

Today "this account has been scrubbed" is inferred from two fields. `accounts/models.py:117`:

```python
if self.deletion_requested_at and not self.is_active:
    return "[deleted]"
```

The inference is wrong in a case that will happen. A user requests deletion on day 0 —
`deletion_requested_at` is set, `is_active` stays `True` so they can log back in and cancel
(ADR-0001). On day 3 a moderator bans them → `is_active=False`. **The scrub has not run.**
`user.name` now returns `[deleted]` while `Profile.bio`, `display_name`, links and the real
avatar are all intact and rendering on every card and comment. The label says deleted; the page
shows the person.

The reverse also holds: a plain ban and a completed scrub are only distinguishable by a
two-field combination that an unrelated moderator action can accidentally satisfy.

One nullable column fixes all of it and buys three more things:

- `name` becomes `if self.anonymised_at: return "[deleted]"` — unambiguous, one field.
- ADR-0001 requires the scrub to be **idempotent** and currently gives the job nothing to key
  on. This is the key.
- Moderation and support can answer "was this deleted or banned, and when" without a join.

**Why now:** `data-model.md` §1.1 opens by saying `User` is "the hardest one in Django to change
later," and `roadmap.md` ground rule 2 exists for the same reason. This is a nullable datetime
in a migration that has not been committed. It will never be cheaper.

---

### 🔴 ACC-2 — the follow note has no path to the notification that should display it

The optional follow note is in `CLAUDE.md`'s vocabulary section and `product-spec.md` §4.4
("Follow — one-way, instant, optional note"). §1.4 models it correctly:
`note = CharField(200), blank`.

*(This answers the "does the follow note have a length limit" question directly: yes, 200, and
it is a genuine database limit because it is `CharField` and not `TextField(N)` — see §0.)*

But §5.1 gives `Notification` nullable concrete FKs to `post`, `comment` and `conversation` —
**and not to `follow`**. So a `new_follower` notification has no way to reach the note. The two
workarounds are both bad:

- `Follow.objects.get(follower=actor, following=recipient)` per bell row — this is precisely the
  N+1 that §5.1's "concrete FKs so we can `select_related`" design exists to prevent.
- It also returns nothing if they have since unfollowed, or if a block hard-deleted the row
  (§1.5) — a notification that cannot render its own content.

```python
follow = models.ForeignKey(
    "accounts.Follow", null=True, blank=True, on_delete=models.CASCADE,
    related_name="notifications",
)
```

`CASCADE` is right here rather than `SET_NULL`: if the follow is gone, a "X followed you, they
said …" notification should go with it. That is correct behaviour on unfollow *and* it gives
ADR-0002's block-time follow deletion the notification cleanup for free.

Cross-seat — this is the `notifications` app, so it goes Jeni → Architect, not me.

---

### 🔴 ACC-3 — `ProfileSkill` / `ProfileInterest` don't specify `on_delete` on the role/tag side

§1.3 describes them as "plain join tables with `created_at`, `UniqueConstraint`, and an index on
the reverse side." §2.4 is explicit for the post-side equivalents: `PostTag` / `PostRole` use
**`PROTECT`** on the tag/role FK — "never let deleting a tag silently strip posts."

The same argument applies to profiles and is not written down, so the default will be picked by
whoever writes 0002. Deleting a `Role` from the admin should not silently strip that skill off
every profile claiming it. Request: `PROTECT` on `ProfileSkill.role` and `ProfileInterest.tag`,
`CASCADE` on the `profile` side, matching §2.4 exactly.

---

### 🔴 ACC-4 — four Meta indexes duplicate an index Django already creates

Django sets `db_index=True` on every `ForeignKey`, and `SlugField` sets it by default too. Each
of these therefore creates a **second, identical** btree index:

| Declared in data-model.md | Already provided by |
|---|---|
| §1.5 `Block` `Index(blocker)` | the FK's own index — and `UniqueConstraint(blocker, blocked)` leads on `blocker` too |
| §1.5 `Block` `Index(blocked)` | the FK's own index |
| §1.2 `Profile` `Index(fields=["field_tag"])` | the FK's own index |
| §1.2 `Profile` `Index(fields=["city_slug"])` | `SlugField.db_index` defaults to `True` |

Write amplification and disk only, no correctness impact — but free to drop pre-lock and a
migration to drop later.

The §1.5 note that "**both** directions are queried, because the effect is symmetric" is
correct and important; it just doesn't require declaring anything, because both columns are FKs
and both are already indexed. `blocked_user_ids()` (ADR-0003) gets its single query either way.

**Not a duplicate, for the record:** `User.username` and `User.email` carry both `unique=True`
and `db_index=True` in `models.py`. Django's schema editor skips the plain index when a field is
unique, so those are harmless noise rather than a second index. No change needed.

---

### 🟡 ACC-5 — anonymise does not touch allauth's tables, so it doesn't actually work

**This is the answer to "does anonymise-on-delete work with allauth?" — as specified, no.**

ADR-0001's table scrubs `User.email` and clears `Profile`. allauth keeps identity in two tables
of its own, and neither is mentioned anywhere in ADR-0001, §8.1, or §10:

- `allauth.account.models.EmailAddress` — one row per address, with `verified` and `primary`.
- `allauth.socialaccount.models.SocialAccount` — `extra_data` JSON holding the Google user id,
  full name, email and profile photo URL. Plus `SocialToken`.

Three consequences, in order of severity:

1. **The real email address and a complete Google identity record survive a scrub that ADR-0001
   describes as "all personal data gone."** That is the privacy story failing at the only point
   where it is load-bearing.
2. `ACCOUNT_UNIQUE_EMAIL = True` (`config/settings/base.py:162`). The surviving `EmailAddress`
   row **permanently blocks that person from re-registering with their own email.** Deleting
   your account locks you out of the product forever.
3. The surviving `SocialAccount` row means "Sign in with Google" matches the dead user. The
   person is bounced into an `is_active=False` tombstone instead of getting a fresh signup.

Fix is service-layer and mine to write — `anonymise_user()` hard-deletes `EmailAddress`,
`SocialAccount` and `SocialToken` inside the same transaction. **But it has to land in ADR-0001's
table**, or QA has nothing to test against and the next person to touch the job will not know.

Two more details for that table while it is open:

- The placeholder email must be unique per user or the second anonymisation collides with the
  first under `unique=True`. Suggest `deleted+<user_id>@alongside.invalid` — `.invalid` is
  RFC 2606 reserved, so it can never route anywhere.
- `User.save()` runs `normalize_email()`, which lowercases **only the domain** (see ACC-13). The
  placeholder is generated, so it is unaffected — noting it so nobody "fixes" it later.

---

### 🟡 ACC-6 — hard-deleted follows drift `follower_count` / `following_count`, with no rule

§7.1 is titled "Soft deletes and counters — the rule that was missing" and covers soft deletes
well. Nothing covers the two places we **hard**-delete follows:

- **Block** (§1.5, ADR-0002): rows in *both* directions, at block time.
- **Anonymisation** (§8.1, ADR-0001): *all* of that user's follow rows.

Each deleted row needs a paired `F()` decrement on two profiles. For anonymisation that is an
N-row update across everyone they followed and everyone who followed them — real work that
nobody has been told to do.

Without a written rule, `follower_count` drifts permanently on every block and every account
deletion. The weekly reconciliation task (§7 rule 4) repairs it, which means **up to seven days
of visibly wrong follower counts** on real profiles, and QA has no rule to assert against.

Requested addition to the §7.1 table:

| Action | Effect |
|---|---|
| Follow hard-deleted (block, unfollow, anonymise) | follower's `following_count` **−1**, followed user's `follower_count` **−1** |

Same `transaction.atomic()` block as the delete, per §7 rule 2.

---

### 🟡 ACC-7 — ADR-0003's safety net does not cover the profile page

ADR-0003 §4 is the mechanism the entire block design rests on, and it is honest about why:
*"'every seat remembers to add a filter' is not a design, it is a hope."* Agreed. But the test is
specified as enumerating *"every authenticated list **URL**"*, and the highest-value block
surface is not a list.

The profile page is a detail view — `get_object_or_404(User, username=...)`. It never touches a
queryset, so `visible_to()` gives it **nothing**. ADR-0002's first table row requires profiles to
404 in both directions; that is a hand-written check in my view, and the test designed to catch
me forgetting it does not cover the URL. Post detail (§1.5, "Direct URL 404s") has exactly the
same shape and the same gap.

`tests/cross/test_block_visibility.py` needs detail URLs as well as list URLs. Flagging for QA
via the Architect, since ADR-0003 is where the contract is stated.

---

### 🟡 ACC-8 — the block list in Settings is a deliberate exception to `visible_to()`

Screen 14 (`roadmap.md` §1.2) includes the block list. It **must** render blocked users' names
and avatars, or there is no way to unblock anyone.

That is the one authenticated surface where the §1.6 filter must *not* apply, and §1.5's framing
— "one rule, no exceptions to remember" — currently implies otherwise. Left unwritten, the block
list reads like a leak and someone will eventually "fix" it into uselessness.

One line in §1.5 next to the surface table is enough. Same category of note as the existing
"moderation and admin use the unfiltered managers on purpose."

---

### 🟡 ACC-9 — `is_public_demo` must also refuse **Block**

§1.1.1 is right that this needs to be a real permission check, and lists the surfaces:
*"403 on create-post, comment and send-message, and success on spark and save."* Block is not
mentioned, and it is the most damaging omission on that list:

- The three public demo accounts are **shared by every visitor** (`testing.md` §7.5).
- Block's effect is global and symmetric (ADR-0002), so one visitor's block changes what every
  later visitor sees from that account.
- Block **hard-deletes follows in both directions, and unblocking never restores them**
  (§1.4). So a single click permanently degrades the seeded demo graph, and `--reset` only
  deletes `is_demo` rows — it does not repair follow edges between surviving seeded users.

Request: add Block to the 403 list in §1.1.1.

**Follow is Jeni's call.** It is reversible and arguably part of the demo experience, but it
dirties seeded `follower_count`s. I lean allow — with the reconciliation task covering the drift
— but I would rather it were written down than left to me.

---

### 🟠 ACC-10 — during the 30-day grace window, is the account visible?

ADR-0001 and the seat brief pull in opposite directions and both cannot hold.

The brief reads *"account deactivated, email/name/avatar/bio scrubbed"* as a single step.
ADR-0001 scrubs at day 30 and says logging back in cancels. But **Django's `ModelBackend`
refuses to authenticate `is_active=False`** — so if we deactivate at request time, the user
cannot log in to cancel, and the grace window does not exist. If instead the account stays fully
active for 30 days, then "delete my account" leaves the profile, photo and bio public for a
month, which most users will read as the button not working.

Three options:

| | Behaviour | Cost |
|---|---|---|
| **A** | Deactivate immediately | Grace window is unreachable. ADR-0001's core promise fails |
| **B** | Fully active for 30 days | Honest to the ADR, but "delete" visibly does nothing for a month |
| **C** | Login still works; profile and posts hidden from everyone immediately; scrub at day 30 | Matches what users expect — **but see below** |

**My recommendation is C, and it has a real cost the Architect needs to price.** No new field is
needed (`deletion_requested_at IS NOT NULL` is the flag), but pending-deletion content must be
hidden from **anonymous** viewers too — and ADR-0003's central optimisation is that
`visible_to()` is a **zero-cost no-op for anonymous users**, which is what keeps the public feed,
the most-hit query in the app, free of visibility logic.

That optimisation is only sound if blocks are the only thing ever hidden. C breaks that
assumption. So this is not just my decision to implement — it reaches into the hottest query
path in the product, and if the answer is C, ADR-0003 needs revisiting before lock.

---

### 🟠 ACC-11 — does an anonymised profile 404 or render a tombstone, and do we release the username?

ADR-0001 retains the username, reasoning that *"it is a foreign key target in URLs and
mentions."* **It is not a foreign key target** — every FK in the schema points at `User.id`.
Nothing breaks if the username changes.

What retaining it does cost:

- `/u/sarah_okafor` resolves forever to an empty `[deleted]` page.
- The handle can never be reused — including by the original person, if they come back.
- Usernames are frequently real names, so a scrub that promises to remove personal data leaves
  the most identifying string in place, in a URL, indexed by search engines.

I would rewrite it to `deleted_<hex>` at scrub time and **404 the profile page**, rendering
`[deleted]` inline everywhere the user is referenced (cards, comments, conversation headers,
notifications) per §8.1. A tombstone profile page listing surviving posts is the one place where
a deleted account still looks like an account, and there is nothing on it to show.

Related, whichever way this goes: `RESERVED_USERNAMES` in `accounts/validators.py` blocks the
exact string `deleted` but not `deleted_1`, so a real user could register a convincing fake
tombstone. That should become a **prefix** rule. My file, cheap, but it is baked into 0001 via
the validator so it is worth doing in the same pass.

---

### 🟠 ACC-12 — onboarding step 2 asks one question and writes two fields

`product-spec.md` §3.1 step 2 is *"What's your occupation or field?"* — one question, free text.
The model has **both**:

- `Profile.occupation` — `CharField(120)`, free text, "for display" (§1.2)
- `Profile.field_tag` — FK to `Tag`, and §1.2 notes only `is_curated=True` tags appear in the
  onboarding field picker

`field_tag` is not decoration: it is the **entire input to Home tier 2** (§3, ADR-0004), which is
the tier ADR-0004 was written to rescue from being permanently empty. Free text will not map to
a curated tag reliably, so either the screen asks twice — making a "3-step" onboarding into four
questions — or we auto-map and it fails often and silently.

**Recommendation:** step 2 shows the curated field picker (populating `field_tag`) with an
optional free-text occupation underneath. No schema change either way, but I need the ruling
before I build the screen, and Discovery needs to know how reliably `field_tag` gets populated.

Two smaller things in the same area, both doc-only:

- **"Skipped" and "never reached" are indistinguishable.** Both leave `onboarding_completed_at`
  null forever, so we either nag someone who deliberately skipped, or never re-prompt someone
  who bounced mid-flow and therefore has no interests — and §2.6 of the spec makes interests the
  thing that carries a brand-new user's Home feed. Proposed fix, no schema:
  **`onboarding_completed_at` means "reached the end of the flow by any path, including
  skipping."** Whether they *answered* is derived from the fields themselves. Every step stays
  skippable (which the model does support — `purpose` blank, `occupation` blank, `field_tag`
  null, interests an empty M2M) and we can still re-prompt the right people.
- **Interests have no cap.** §1.2 documents "Max 3" for `custom_skills` and nothing for
  `ProfileInterest`, so Home tier 1 could be handed a 200-tag `IN` clause. Suggest documenting a
  form-level cap of 10 so Discovery can plan tier 1 against a known bound.

---

### ⚪ ACC-13 — email case-sensitivity is a live bug in shipped code

`accounts/models.py:106`:

```python
self.email = self.__class__.objects.normalize_email(self.email)
```

`normalize_email()` lowercases **only the domain part**. So `Jeni@x.com` and `jeni@x.com` are two
distinct rows under `unique=True`, while allauth compares full-lowercase in several paths. The
result is both failure directions at once: duplicate signups that should have collided, and
confusing "an account with that email already exists" errors where Django's constraint says
otherwise.

The username immediately above it is handled correctly (`.lower().strip()`); email should match.
Local-parts are technically case-sensitive per RFC 5321, but every consumer product lowercases
them and allauth effectively assumes it.

`models.py` is the Architect's file, so flagging rather than fixing.

---

### ⚪ ACC-14 — `User.Meta.ordering` leaks into every query

`ordering = ["-date_joined"]` applies to joins, subqueries and aggregates, not just the queries
that want it — the standard Django footgun where a default ordering shows up in a `GROUP BY` and
quietly changes a plan. Views that want it can say so. Free to drop pre-lock.

---

## 2 · Summary

| # | Type | Change | Owner |
|---|---|---|---|
| ACC-1 | 🔴 | Add `User.anonymised_at` | Architect, 0001 |
| ACC-2 | 🔴 | Add `Notification.follow` FK | Architect, `notifications` |
| ACC-3 | 🔴 | `PROTECT` on `ProfileSkill.role` / `ProfileInterest.tag` | Architect, 0002 |
| ACC-4 | 🔴 | Drop 4 redundant Meta indexes | Architect, 0002 |
| ACC-5 | 🟡 | ADR-0001: scrub `EmailAddress` / `SocialAccount` / `SocialToken` | Doc → me |
| ACC-6 | 🟡 | §7.1: counter rule for hard-deleted follows | Doc → all seats |
| ACC-7 | 🟡 | ADR-0003 §4: safety net must cover detail URLs | Doc → QA |
| ACC-8 | 🟡 | §1.5: block list is an explicit `visible_to()` exception | Doc → me |
| ACC-9 | 🟡 | §1.1.1: `is_public_demo` also 403s Block | Doc → me |
| ACC-10 | 🟠 | Grace-window visibility — **may change ADR-0003** | **Jeni** |
| ACC-11 | 🟠 | Anonymised profile: 404 vs tombstone; release the username? | **Jeni** |
| ACC-12 | 🟠 | Onboarding step 2 shape; `onboarding_completed_at` semantics; interest cap | **Jeni** |
| ACC-13 | ⚪ | Lowercase the whole email in `User.save()` | Architect, `models.py` |
| ACC-14 | ⚪ | Drop `User.Meta.ordering` | Architect, `models.py` |

Nothing here needs a rewrite. ACC-1 to ACC-4 are small and pre-commit. ACC-5 to ACC-9 are lines
in documents that already exist. The only genuinely hard one is **ACC-10**, because the honest
answer may cost ADR-0003 its anonymous fast path — and that is a decision worth making
deliberately rather than discovering in Phase 6.

**Not blocked meanwhile.** While this is reconciled I can work in files I own: the
`anonymise_user()` service signature (ADR-0001 action item 3), the allauth adapter that
normalises Google-derived usernames against `[a-z0-9_]{3,30}` (flagged as mine in §10), and the
`deleted_` prefix reservation in `validators.py`.
