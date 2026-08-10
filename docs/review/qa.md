# Data-model review — QA & Seed Data seat

**Reviewer:** QA · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock) + `adr/0001`–`0004`
**Method:** two passes. (1) Can every rule in the doc actually be **asserted** — and what states
does the schema permit that the product forbids? (2) Walked the seed command field by field
against every model it has to write. Full detail in `docs/testing.md` §10.

**Headline:** the model is testable and I'd build against it. **11 findings.** Three are schema
changes I'd argue must land before lock, one of which touches `accounts` 0001 and therefore
gets more expensive than everything else the moment the migration is locked. Two are decisions
only Jeni can make. The rest are contracts.

| # | Change | Why it can't wait |
|---|---|---|
| **1** | `User.anonymised_at` | On the auth table — retrofitting means a migration on `User`. Without it ADR-0001's idempotency requirement is unassertable and two wrong states are reachable |
| **2** | `Notification` kind↔target `CheckConstraint` | Renders on every page load; the schema currently permits rows that link nowhere |
| **3** | `PostImage.image_url` | Same gap `avatar_url` was added to close, one model over. Without it the seed cannot put a single image on the demo site |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a field or constraint before lock |
| 🟠 **Decision** | Product question for Jeni, or a doc rule that needs a specific answer |
| 🟡 **Contract** | No new column; an interface or convention seats depend on and nobody has written down |
| ⚪ **Noted** | Fine as-is. Recorded so it isn't re-reviewed, or so nobody "fixes" it |

---

## 1 · Findings

### 🔴 1 — `User` has no field recording that anonymisation happened

ADR-0001 requires the scrub to be **idempotent** and run in one transaction. Nothing in the
schema records that it ran. The state is inferable only as
`deletion_requested_at IS NOT NULL AND is_active = False`, and that inference is wrong in two
reachable ways:

- **Ban collides with deletion.** `data-model.md` §1.1 says `is_active=False` means
  "deactivated, banned, **or** deleted". A user who requests deletion on day 1 and is banned by
  moderation on day 3 satisfies both halves — `User.name` starts returning `[deleted]` across
  every card, comment and conversation header while their bio, avatar and links are still on
  screen, 27 days before the scrub was due.
- **A half-scrubbed row is never retried.** The job clears ~12 `Profile` fields. If it fails
  partway after setting `is_active=False`, the row no longer matches its own selection query, so
  it is skipped forever and stays half-anonymised.

```python
anonymised_at = models.DateTimeField(null=True, blank=True, db_index=True)
```

Fixes both, makes the job's query honest
(`deletion_requested_at <= now-30d AND anonymised_at IS NULL`), makes `User.name` a
single-field check, and reduces the idempotency test to two lines.

**Why now specifically:** every other ask on this page is a normal migration. This one is on the
swapped `AUTH_USER_MODEL` table, which is the one place the roadmap's ground rule 2 exists to
keep us out of.

---

### 🔴 2 — `Notification` permits rows that point at nothing

`Report` got `CheckConstraint`: exactly one of `reported_user` / `post` / `comment` non-null.
`Notification` has the same shape — `kind` plus three nullable concrete FKs — and got no
constraint at all. So these all insert cleanly today:

| Row | Result in the UI |
|---|---|
| `kind='new_comment'`, `comment=NULL` | bell entry linking nowhere, or a template crash on `.comment.body` |
| `kind='new_message'`, `conversation=NULL` | same, on the highest-volume notification kind |
| `kind='new_follower'`, `post=<some post>` | silently wrong target |

This is the one table rendered on **every authenticated page load** (§5.1's partial unread
index exists because of that), so a bad row is a site-wide 500 rather than one broken screen —
and it surfaces during a demo, not in a test, because nothing forbids writing it.

One constraint, three OR'd `Q` clauses, same pattern already accepted for `Report`:

```
(kind='new_follower' AND post IS NULL AND comment IS NULL AND conversation IS NULL)
OR (kind='new_comment'  AND comment IS NOT NULL AND post IS NOT NULL)
OR (kind='new_message'  AND conversation IS NOT NULL)
```

> Related, and I agree with the Designer's GAP 13: if `stale_nudge` becomes a fourth kind, it
> needs a clause here in the same commit. Also confirming their footnote — `CheckConstraint`
> on `recipient != actor` is satisfied by `actor=NULL`, so system-generated rows are fine.

---

### 🔴 3 — `PostImage` can't be seeded

`PostImage.image` is a `CloudinaryField` with no URL sibling. That is exactly the problem
§1.2.1 solved for avatars, and the reasoning transfers unchanged: uploading from the seed
command is slow, credential-dependent and **not idempotent**, which breaks the `--reset`/re-run
contract in `testing.md` §7.4.

Consequence if it stays: the demo ships 45 text-only posts, the `PostImage` render path is
never exercised on the live site, and the crochet-business case — the one `product-spec.md` §1
names by hand — has no picture. A feed of pure text reads noticeably thinner than the product
is.

Ask: mirror the avatar fix.

```python
image_url = models.URLField(blank=True)     # + display_url property, same precedence rule
```

Seed points it at ~5 images committed under `static/demo/`, used across ~8 posts. Zero runtime
third-party dependency, deterministic, and WhiteNoise already serves it.

---

### 🟠 4 — `Post.last_activity_at` has no stated default or nullability

Listed as `DateTimeField, indexed`. If that is non-null with no default, **every**
`Post.objects.create()` that omits it raises — every factory, the seed, and the Posts seat's
create view. If it is nullable, the stale-nudge job's `Index(-last_activity_at)` sorts nulls
and the job's window arithmetic has a null case nobody has thought about.

Not a new column — just say which, in the field table. My preference: **non-null,
`default=timezone.now`**, bumped by spark/comment/edit as already specified. Then the stale job
never sees a null and the seed sets it explicitly for realistic dates.

---

### 🟠 5 — "guard the decrement" needs to say *how*

§7 rule 3 says `PositiveIntegerField` + "guard the decrement so it can never go below zero".
Two things that rule doesn't cover, and both produce user-visible failures:

- **A plain `F("comment_count") - 1` on a row already at 0 raises `IntegrityError`.** Django
  emits a Postgres `CHECK (col >= 0)` for `PositiveIntegerField`, so the "guard" cannot be a
  Python read-then-write (that reintroduces the race rule 1 forbids) — it has to be in SQL:
  `Greatest(F("comment_count") - 1, 0)`. Written the obvious way, the first user to delete a
  comment on a post whose counter has drifted low gets a 500 from the delete button.
- **Soft-delete must be idempotent.** §7.1 says soft-deleting a comment decrements
  `Post.comment_count`. Nothing says the delete path must no-op when `deleted_at` is already
  set, so a double-submit or a retried request decrements twice and the post shows 10 comments
  over 11 rendered rows — which reads as a caching bug and isn't.

Both are one sentence each in §7. They affect Social, Posts and Messaging identically, which is
why they belong in the shared doc rather than in three seats' heads.

---

### 🟠 6 — `demo.mod@` publishes a staff password, and `is_public_demo` doesn't gate admin

`testing.md` §7.5 wants a staff account with **credentials printed on the login screen** so the
moderation queue is demonstrable. `is_public_demo` is an application-layer permission check;
**Django admin does not consult it.** As specified, anyone reading the login screen can open
`/admin/`, delete every row in the database, and change other users' passwords.

No schema change needed — but it needs a decision and a seeded object:

1. Seed a `demo_moderator` **Group** holding exactly `moderation.view_report` and
   `moderation.change_report`, assign `demo.mod@` to it, grant nothing else, `is_superuser=False`.
   I then assert no `delete_*` permission on any installed model (iterated, not hand-listed) and
   403 on `/admin/accounts/user/`.
2. Or don't publish that account, and show the queue in README screenshots.

Either is testable. The current specification is not something I can make safe from the test
side alone. **Jeni's call.** If (1), the Group belongs in a data migration next to the curated
tags and roles so it exists identically in every environment.

---

### 🟠 7 — "Home is never empty" is not assertable as written

`product-spec.md` §4.3's guarantee is the thing my brief names by hand, and three gaps stop it
being a test:

1. **Union or fallback?** Tier 1 returns 3 posts and the page wants 20 — does Home show 3, or
   3 + 17 from tier 2? Different products, different assertions. *Rec: top up to a target,
   tiers in order, deduped.* Pure fallback means one follow gives a one-post Home forever.
2. **What is the target?** Without a number there is no boundary to test. *Rec: 20.*
3. **"≥1 post" or "≥1 visible post"?** A database with exactly one post that is soft-deleted,
   or `team_formed`, or authored by a block-related user gives an empty Home however good the
   cascade is. *Rec: the guarantee is over `deleted_at IS NULL AND status='looking'` and
   block-filtered rows; the zero-visible case renders the empty state — asserted as a 200.*

Jeni + Discovery. No schema impact.

---

### 🟡 8 — Home must report which tier filled the page

ADR-0004 action item 6 makes me assert **tier 2 specifically returns rows**, because the
`Tag.kind` bug was invisible precisely by falling through to tier 3 with Home still looking
full. From outside the view, two tiers returning overlapping posts are indistinguishable — the
best I can do is construct data where tier 3 would have returned *different* rows, which proves
the rows appeared, not that tier 2 ran.

A `home_tier` value in the template context makes the assertion direct and doubles as a live
debugging aid.

> **The Designer asked for the same thing independently (their GAP 4), for a different reason —
> the per-band labels on the cold-start screen.** Two seats needing it from opposite ends is
> probably the strongest case for writing it into §3 next to the cascade table.

---

### 🟡 9 — `dyad_key` isn't tied to the conversation's actual participants

`UniqueConstraint(dyad_key)` prevents duplicate 1:1 conversations, which is the race it exists
for and it works. But nothing connects the key to the `ConversationParticipant` rows: the schema
permits `dyad_key='3:7'` on a conversation whose participants are 3 and 9, after which
get-or-create for (3, 7) hands user 7 a thread they are not in — a message-disclosure bug that
reads as a messaging feature working normally.

Cross-table, so not cheaply constrainable. That is the argument for a single
`Conversation.objects.get_or_create_dyad(a, b)` writing the key and both participants in one
transaction — same shape as the `visible_to()` decision in ADR-0003, and for the same reason:
the invariant gets one owner and one test instead of living in whichever view calls it.

---

### 🟡 10 — optional: `CheckConstraint(last_activity_at >= published_at)`

Expressible with `F()`, and both the stale job and feed ranking assume it. It would make a seed
bug fail loudly instead of shipping posts whose "last activity" predates their existence. Cheap;
say no if you'd rather not carry it. I test the invariant either way.

---

### 🟡 11 — search vectors are populated by a task, which has two consequences nobody owns

§3 says `search_vector` is refreshed on save **via a Celery task**. Two follow-ons:

- **Test settings must set `CELERY_TASK_ALWAYS_EAGER=True`**, or every search test fails with an
  empty result set and no visible cause. (Prod already runs eager on the free tier, so this also
  matches prod — worth a line in §3.)
- **`bulk_create` does not fire `post_save`.** Anything the seed bulk-inserts ships with a null
  vector, which means **search returns nothing on the deployed site** while every unit test of
  the extractor passes. Handled on my side by an explicit recompute pass and an assertion
  (`testing.md` §7.3), flagged here because the same trap is waiting for any seat that bulk-loads.

---

## 2 · Seed field inventory

Everything `seed_demo` has to write. Unmarked = the field exists and is writable.

| Model | Fields the seed sets | Gap |
|---|---|---|
| `User` | username · email · password · display_name · `date_joined` *(writable — varied join dates)* · `last_seen_at` · `is_demo` · `is_public_demo` | — |
| `Profile` | bio · headline · occupation · city/`city_slug` · `work_done` · 3 links · `field_tag` · `purpose` · `custom_skills` · interests ⇄ Tag · skills ⇄ Role · `onboarding_completed_at` · **`avatar_url`** | — *(resolved my Q12)* |
| `Post` | title · body · slug · stage · commitment · status · city · `published_at` *(writable — the 90-day spread)* · `last_activity_at` · `is_stale` · tags · roles · `custom_roles` · `keywords` | **finding 4** |
| `PostImage` | — | **finding 3 — blocked** |
| `Comment` · `PostSpark` · `CommentSpark` · `SavedPost` · `Follow` (+`note`) | all present | — |
| `Conversation` · `ConversationParticipant` · `Message` | `dyad_key` · `last_message_at`/`_preview` · `last_read_at` · body · created_at | **finding 9** *(and Designer's GAP 12 `last_message_sender`, which the seed would also populate)* |
| `Notification` | kind ×3 · actor · target FK · `is_read` | **finding 2** |
| `Report` | reporter · one target · reason · details · status | — |
| Groups | `demo_moderator` | **finding 6** |

`Tag` and `Role` deliberately have no `is_demo` and I'm **not** asking for one — `--reset`
reconciles `post_count` and drops non-curated tags that end at zero, and curated rows from the
`posts` 0002 data migration must survive a reset regardless.

---

## 3 · Things I checked that are fine — and two nobody should "fix"

- **`is_demo` / `is_public_demo` split (§1.1.1)** — correct, and it fixed a real error in my own
  v1 doc. ⚠️ **Do not enforce `is_public_demo` in `Model.save()` or a signal.** The demo
  account's 3 posts, 2 conversations and sent messages are written *by the seed command*; a
  model-layer block leaves the flagship demo account empty. Request layer only. (Flagged to
  Accounts via Jeni; recorded here so it isn't "tightened" later.)
- **Block is a soft barrier, not an access control (ADR-0002)** — I have a test asserting a
  blocked user's public content **is still visible logged out**, so the day someone reports that
  as a privacy bug, the test says it's deliberate. Please leave it red-flagged in the ADR.
- **Counters global, never viewer-relative (§7.2)** — asserted identical before and after a block.
- **`dyad_key` nullable so NULLs don't collide** — correct Postgres behaviour and worth having;
  pinned by a test so nobody makes it non-null "for tidiness".
- **`Report` conditional uniques** — the condition is the right call. I test both directions:
  a second *open* report raises, and a report **after a dismissal succeeds**.
- **`TextField(N)` is form-level only (§0)** — understood; no test asserts a DB limit that isn't
  there. Same for max 5 images and max 3 custom roles/skills — form-level, correctly so, and I'm
  not asking for check constraints on any of them.
- **`Message.sender` isn't constrained to be a participant** — cross-table, not worth a trigger.
  Covered at the view layer in the permission matrix (POST to a conversation you're not in →
  403/404 **and no row**).
- **No `view_count`** — agreed, and nothing in the suite references it.
- **Concrete nullable FKs on `Notification` over a GenericForeignKey** — right call; the query
  budget suite pins that `select_related` is actually used.
- **`published_at` writable and separate from `created_at` (§2.3.1)** — this is the single field
  that makes the demo not look fake. Thank you for it.

---

## 4 · What I need back

1. **Three schema changes** — findings 1, 2, 3. **Finding 1 is the only one that gets materially
   more expensive after lock**, since it's on `User`.
2. **Two decisions from Jeni** — finding 6 (publish a staff password, or don't) and finding 7
   (what "never empty" means).
3. **Three lines in the doc** — finding 4 (`last_activity_at` default), finding 5 (`Greatest()`
   + idempotent soft-delete), finding 11 (eager Celery in tests, bulk_create skips signals).
4. **Two contracts** — finding 8 (`home_tier`, which the Designer needs too) and finding 9
   (`get_or_create_dyad`).
5. Finding 10 is take-it-or-leave-it.

Everything else I'd build against as-is.
