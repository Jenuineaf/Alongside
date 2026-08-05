# Alongside — Test Strategy, Conventions & Seed Data

> **Alongside** — nobody builds alone.

**Status:** 🟡 **v2 — PROPOSAL, AWAITING CEO SIGN-OFF.**
**Author:** QA seat · **Written:** 31 Jul 2026 · **Revised:** 31 Jul 2026 (v2)
**Companion to:** `product-spec.md`, `tech-stack.md` §9, `roadmap.md`, `data-model.md` (approved),
`adr/0001`–`adr/0004`, `deployment.md` §6

Once approved this file is the contract for how every seat writes tests. Feature seats write
tests in their own area; QA owns the conventions, the factories, the cross-cutting suites, and
the seed data.

**What changed in v2.** `data-model.md` is approved and all eleven of its open questions are
answered, which unblocks almost everything v1 listed as blocked. Specifically:

| Change | Where it lands here |
|---|---|
| `is_demo` **split into** `is_demo` (seed lineage) + `is_public_demo` (write restriction) | §7.4, §7.5 — the write-block now keys off `is_public_demo` only |
| Avatars unblocked — `Profile.avatar_url` + `avatar_display_url` | §7.7, §2.1 |
| Block = full mutual invisibility; chat hidden not deleted, restored on unblock | §5.5 (new suite), §6 |
| Account deletion = anonymise, 30-day grace, content survives as `[deleted]` | §6 |
| Comments not editable, deletable; soft-delete decrements `comment_count` | §2.2, §5.1 |
| Sparks do not notify (only new DM / new follower / new comment) | §7.5, §2.1 |
| `view_count` cut | no tests written for it, ever |
| Roles curated + "Other" free text; tags user-created free text | §7.1 corpus, §5.1 |
| Stale posts ranked lower, never hidden | §6 |

The Architect's skeleton **has landed** — `manage.py`, `config/`, `accounts` 0001 and
`tests/test_skeleton.py` all exist. §11 is now a work list, not a waiting list.

---

## 1. The three rules

Everything below follows from these.

**1. Tests run against the migrated schema. Always.**
No `--no-migrations`. No `--nomigrations`. No fixture that builds tables from
`Model._meta` instead of running the migration chain. DevOps already put
`makemigrations --check --dry-run` in CI (`deployment.md` §6) for exactly this reason, and
asked QA to hold the line. Holding it.

*Why this is rule one:* on SpendWise the test suite built its schema with
`Base.metadata.create_all` instead of running migrations. Model/migration drift became
structurally invisible — the suite was green while production 500'd on a missing column. The
tests were not wrong; they were testing a schema that did not exist anywhere else. That is the
most expensive class of bug there is, because it disables the thing meant to catch it.

**2. Postgres, never SQLite.**
`SearchVectorField`, `ArrayField`, `GinIndex`, partial indexes, `CheckConstraint` with `F()`,
partial `UniqueConstraint`, and `pg_trgm` all either don't exist or silently no-op on SQLite. A
suite that passes on SQLite proves nothing about this app. Local and CI both run Postgres 16.

**3. A constraint that is never tested is decoration.**
`data-model.md` declares ~20 `UniqueConstraint`s and `CheckConstraint`s. Nothing in normal
feature code proves they reached the database. See §5.1.

---

## 2. What gets unit tested vs integration tested

| Layer | Marker | DB? | What lives here |
|---|---|---|---|
| **Unit** | none | ❌ | Pure functions. Fast, exhaustive, table-driven |
| **Model / integration** | `@pytest.mark.django_db` | ✅ | ORM behaviour, constraints, managers, counters |
| **View** | `@pytest.mark.django_db` + client | ✅ | Permissions, status codes, redirects, HTMX partials, forms |
| **Cross-cutting** | `@pytest.mark.django_db` | ✅ | Permission matrix, public-read matrix, block visibility, N+1 budgets, seed |
| **Device** | `browser` | — | Manual browser checks, §8. Not pytest |

### 2.1 Unit — no database, and there should be a lot of these

Anything that is a function of its inputs gets tested without touching Postgres. These run in
milliseconds, so they get exhaustive edge cases rather than one happy path.

| Function | Owner seat | The edges that matter |
|---|---|---|
| Keyword extraction from title + body | Discovery | empty body · body of stopwords only · emoji · Devanagari/non-ASCII · 5000 words · a single 200-char word · HTML-looking input · duplicate keywords · casing |
| Username validation + reserved blocklist | Accounts | `admin` · `API` (case) · 2 chars · 31 chars · `a_b` · unicode homoglyphs · leading/trailing `_` |
| Post slug generation | Posts | duplicate titles · title that slugifies to `""` (all emoji, all Devanagari) · 140-char title vs 160-char slug field · **stability across edits** · the random suffix (see §7.4 note 3) |
| `city_slug` normalisation | Accounts/Posts | "Bengaluru" vs "bengaluru" vs "BLR " · accents · empty |
| `dyad_key` computation | Messaging | order-independence: `f(a,b) == f(b,a)` · same user twice · fits `CharField(40)` at 19-digit ids |
| `last_message_preview` truncation | Messaging | exactly 140 chars · 141 · newlines · emoji on the 140th byte (never split a codepoint) · empty body |
| `Profile.avatar_display_url` precedence | Accounts | upload set → upload wins · upload blank + `avatar_url` set → url · both blank → `DEFAULT_AVATAR`. **Never returns `""`** |
| `User.name` / `[deleted]` rendering | Accounts | display_name · blank display_name → username · anonymised → `[deleted]` (§10 Q-A) |
| Notification dedup windows | Social | **comments:** exactly 60s · 59s · 61s · different actor · different post. **messages:** existing unread row → bump, not insert · existing *read* row → insert |
| Stale-post date arithmetic | Trust & Safety | exactly 30 days · DST-free UTC assumption · already-nudged · author replied |
| Rate-limit key derivation | Trust & Safety | anonymous vs authenticated · proxy `X-Forwarded-For` |

**Discovery's keyword extraction gets the deepest unit test in the repo.** It is the star
feature (`roadmap.md` Phase 3) and it is a pure function — there is no excuse for it to be
shallowly tested. Table-driven, one row per input, ~30 rows.

### 2.2 Model / integration — the ORM actually did what we said

- Every constraint from `data-model.md` raises `IntegrityError` (§5.1).
- Soft-delete: `objects` excludes `deleted_at`-set rows, `all_objects` includes them, for
  `Post`, `Comment`, `Message`. Plus: a soft-deleted post's comments are still reachable by
  moderation, and a soft-deleted post 404s publicly.
- Counters (`data-model.md` §7): `spark_count` after N concurrent-ish sparks equals N;
  unsparking decrements; **never goes below zero**; the weekly reconciliation task repairs
  deliberately-corrupted counters back to truth.
- **Soft-delete counter rules (`data-model.md` §7.1), one test each:** soft-deleting a comment
  decrements `Post.comment_count`; soft-deleting a post decrements the author's
  `Profile.post_count` and every `Tag.post_count` on it; undelete reverses each; a
  soft-deleted post's sparks and saves are **not** touched.
- **Double-decrement is the bug to chase here.** Soft-deleting an already-soft-deleted comment
  must be a no-op, and the decrement must be expressed in SQL as
  `Greatest(F("comment_count") - 1, 0)`, never a Python read-then-write. A plain
  `F("comment_count") - 1` on a row already at 0 raises `IntegrityError` against the
  `PositiveIntegerField` check and 500s the delete button. Two tests: delete twice → count
  down by one; delete a comment on a post whose counter is already 0 → no exception.
- `Profile` is created exactly once per `User`, in the same transaction, and survives
  `get_or_create` being called twice.
- Cascade behaviour: deleting a `Post` removes its `PostTag` rows but **not** the `Tag`
  (PROTECT); deleting a `Tag` that is in use raises.
- `search_vector` is non-null after a save (see §7.3 — the seed's most likely silent failure).

### 2.3 View — status codes and who is allowed

Django test client, not Selenium. Every feature seat writes these for their own views. The
shape is fixed so they're comparable:

```python
def test_edit_post_rejects_non_author(client, post, other_user):
    client.force_login(other_user)
    response = client.post(reverse("posts:edit", args=[post.slug]), VALID_DATA)
    assert response.status_code == 403
    post.refresh_from_db()
    assert post.title == "Original title"     # assert the side effect, not just the code
```

**The second assertion is the point.** A 403 with the write still having happened is a real
bug that a status-code-only test passes. Every permission test asserts the object did not
change.

**HTMX responses:** partials are tested by asserting the response is the fragment and not the
whole page — `assertTemplateUsed(response, "posts/_card.html")` and
`assert "<html" not in response.content.decode()`. An HTMX endpoint that accidentally returns
the full page still looks fine in the browser and doubles every payload.

---

## 3. Directory layout — one owner per directory

```
tests/
├── conftest.py              # QA — global fixtures, Faker seeding
├── test_skeleton.py         # QA — absorbed from the Architect's skeleton
├── factories/               # QA — single source of truth for all factories
│   ├── __init__.py          #      re-exports everything
│   ├── accounts.py
│   ├── posts.py
│   ├── messaging.py
│   ├── notifications.py
│   └── moderation.py
├── cross/                   # QA — the suites no single seat owns
│   ├── test_constraints.py
│   ├── test_permission_matrix.py
│   ├── test_public_access.py
│   ├── test_block_visibility.py     # NEW in v2 — ADR-0003 action item 4
│   ├── test_query_budgets.py
│   └── test_seed_demo.py
├── accounts/                # Accounts & Profiles seat
├── posts/                   # Posts & Feed seat
├── discovery/               # Discovery seat
├── social/                  # Social seat
├── messaging/               # Messaging seat
└── moderation/              # Trust & Safety seat
```

**Why a top-level `tests/` rather than `<app>/tests/`:** ten seats sharing a repo need one
directory per owner and no shared files. Per-app test packages force every seat through the
same `conftest.py` and the same factory module — which is precisely the collision the seat
model exists to prevent. This way, the only files two seats both touch are the factories, and
those have one owner: me.

**Factories are QA-owned.** Need a new factory or a new trait? Ask through Jeni. It takes me
two minutes and it stops five near-identical `PostFactory`s appearing in five directories.

---

## 4. Factory conventions

`factory_boy` 3.3 + `Faker` 33 (already in `requirements/dev.txt`).

### 4.1 The rules

**1. Faker fills what the test ignores. Tests assert on explicit values.**

```python
post = PostFactory(title="Crochet studio needs a website")   # asserted → explicit
# body, city, published_at → Faker, because this test doesn't care
```

Never assert on a Faker-generated value. That is how you get a suite that fails once a month
for no reason and gets `-x`'d into irrelevance.

**2. Faker is seeded.** `conftest.py` calls `Faker.seed(0)` and `random.seed(0)` per session,
so a failure reproduces from the same command. Non-reproducible failures get ignored, and
ignored failures are worse than no test.

**3. `django_get_or_create` on anything with a unique key** — `Tag.slug`, `Role.slug`,
`User.username`. Without it, the second `TagFactory(slug="fintech")` in a test blows up with
an `IntegrityError` that has nothing to do with what's being tested.

**4. Traits, not subclasses.**

```python
PostFactory(team_formed=True)      # status="team_formed"
PostFactory(stale=True)            # is_stale=True, last_activity_at=90 days ago
PostFactory(deleted=True)          # deleted_at set
PostFactory(with_tags=["ai", "fintech"])
UserFactory(seeded=True)           # is_demo=True          — data lineage only
UserFactory(public_demo=True)      # is_demo + is_public_demo — the write-restricted accounts
UserFactory(onboarded=True)        # profile filled + onboarding_completed_at set
UserFactory(deleting=True)         # deletion_requested_at set, still inside the grace window
UserFactory(anonymised=True)       # post-scrub state — renders as [deleted]
```

Ten trait flags on one factory beat ten factory subclasses nobody can keep straight.

**`demo=True` is gone.** It was ambiguous the moment the flag split, and an ambiguous trait
name on a permission-relevant field is how a test ends up asserting the wrong thing while
looking correct. `seeded=` and `public_demo=` say which one they mean.

**5. Counter fields are never set directly by default.** If a test cares about
`spark_count`, it creates real `PostSpark` rows and lets the application's `F()` update run.
Setting `spark_count=42` in a factory means the test passes even if the increment logic is
broken — which is the only thing worth testing about a denormalised counter. There is one
escape hatch, `PostFactory(spark_count_override=42)`, explicitly named so it's obvious in a
diff, and it is only for display/ordering tests.

**6. `UserFactory` must not create a `Profile`.** `data-model.md` §1.2 creates it via
`post_save`. A factory that also creates one either duplicates it or masks the signal being
broken. `UserFactory` instead *updates* the auto-created profile in `post_generation`, and
there is a test that a bare `User.objects.create_user()` has exactly one profile.

**7. `SubFactory` for FKs, `post_generation` for M2M.** M2M accepts a list of existing
objects or a list of slugs it will `get_or_create`.

**8. `avatar` is never populated by a factory; `avatar_url` may be.** `CloudinaryField` in a
factory means either a network call or a mock in every test that touches a profile. Factories
set `avatar_url` to a deterministic local path and leave `avatar` blank. The one test that
covers the upload-wins branch of `avatar_display_url` constructs the object in memory (§2.1)
rather than uploading anything.

### 4.2 Global fixtures (`tests/conftest.py`, QA-owned)

| Fixture | Gives you |
|---|---|
| `user` | one ordinary onboarded user |
| `other_user` | a second, for permission tests |
| `blocked_pair` | `(a, b)` with a `Block` row from a → b, cache invalidated |
| `anonymous_client` | `Client()`, never logged in |
| `auth_client` | `Client()` logged in as `user` |
| `post` | a published post authored by `user` |
| `populated` | a small realistic world: 5 users, 12 posts, tags, follows, sparks, comments |
| `frozen_now` | freezegun at a fixed instant — see §9 |
| `no_rate_limits` | autouse; disables `django-ratelimit` so §6's limits don't fail everyone else's suite |
| `clear_cache` | autouse; flushes the Redis/locmem cache between tests so a stale block set never leaks across tests |

`populated` is the fixture that makes feed, search, and Home-fallback tests readable. It is
built from the *same corpus* as the seed command (§7), so a test failure is debuggable against
data you have actually seen in the browser.

`clear_cache` is not optional bookkeeping. ADR-0003 caches the block set per user in Redis;
without a flush between tests, test B inherits test A's block set and fails in a way that
depends on test ordering — the single most expensive kind of flake to diagnose.

---

## 5. The five cross-cutting suites (QA-owned)

These are the ones no feature seat would write, and they are where the value is.

### 5.1 `test_constraints.py` — every declared constraint, proven

One test per `UniqueConstraint` and `CheckConstraint` in `data-model.md`, each asserting
`IntegrityError`:

- `Follow` unique(follower, following) · no self-follow
- `Block` unique(blocker, blocked) · no self-block
- `PostSpark` unique(user, post) · `CommentSpark` unique(user, comment)
- `SavedPost` unique(user, post)
- `PostTag` unique(post, tag) · `PostRole` unique(post, role)
- `ProfileSkill` unique(profile, role) · `ProfileInterest` unique(profile, tag)
- `Conversation.dyad_key` unique — **and** a test that two get-or-creates for the same pair
  produce one conversation, which is the actual race the key exists to prevent
- **`Conversation.dyad_key` NULL does *not* collide** — two group-shaped conversations with a
  null key both insert. That is the whole reason it is nullable (`data-model.md` §4.1), and it
  is Postgres-specific behaviour worth pinning
- `ConversationParticipant` unique(conversation, user)
- `Notification` recipient != actor
- `Report` — exactly one of `reported_user` / `post` / `comment` is non-null
- `Report` conditional uniques, **both directions**: a second *open* report by the same
  reporter on the same target raises; a second report **after the first was dismissed
  succeeds**. The second assertion is the one that matters — it proves the `condition=` is
  actually on the index rather than the constraint having quietly become "one report ever"
  (`data-model.md` §6.1)
- `User.email` unique · `User.username` unique · `Tag.slug` unique · `Role.slug` unique
- Every counter field rejects a negative value (`PositiveIntegerField` → Postgres `CHECK >= 0`)
- `PostTag.tag` / `PostRole.role` are `PROTECT`: deleting an in-use tag raises

~25 tests, all four lines long, written once. They catch a migration that silently dropped a
constraint, which `makemigrations --check` cannot: that check compares models to migrations,
not migrations to the actual database.

### 5.2 `test_permission_matrix.py` — the single most valuable file in the suite

One parametrised matrix instead of permission tests scattered across six directories.

Actors: `anonymous` · `owner` · `other_user` · `block_related` · `staff` · `public_demo` (§7.5)
Objects: post · comment · profile · conversation · message · report
Actions: view · create · edit · delete · spark · save · message

Each cell declares an expected status. Adding an action means adding a row, and every actor is
covered for free. When a seat ships a view that forgets `@login_required` or forgets to check
ownership, this file goes red — not the seat's own tests, which will have tested the happy
path they were thinking about.

Every destructive cell also asserts the object is unchanged afterwards (§2.3).

**Three cells that are easy to miss and are in the matrix by name:**

- **Comments cannot be edited by anyone**, including their author (`data-model.md` §2.6). There
  is no edit view; a POST to a guessed URL is a 404/405 and the body is unchanged.
- **A user POSTing a message into a conversation they are not a participant of** → 403/404 and
  **no `Message` row**. The schema cannot enforce that `sender` is a participant (§10 Q-D), so
  this test is the enforcement.
- **Sparking or commenting on a soft-deleted post** → 404, no row. The schema allows it; the
  product does not.

### 5.3 `test_public_access.py` — the login wall never comes back

`product-spec.md` §5.2 and `CLAUDE.md` rule 7 call public read access non-negotiable. It is
also exactly the kind of thing that breaks by accident when someone adds `LoginRequiredMixin`
to a base view.

An explicit table of every URL name → expected anonymous status:

| URL | Anonymous expects |
|---|---|
| landing, feed, post detail, profile, search results, tag page, role page | **200** |
| home, create post, messages, chat, notifications, saved, settings, onboarding | **302 → login** |
| spark, comment, follow, DM send | **302 or 403, and no row created** |

The table is the spec. If a URL isn't in it, the test fails — so a new view cannot be added
without someone deciding, on the record, whether the public can see it.

### 5.4 `test_block_visibility.py` — new in v2, and the leak nobody owns

ADR-0003 hands this to QA by name, and the reasoning is the reason it exists: Block is
symmetric and global, roughly a dozen authenticated read paths need the filter, six seats own
them, and **a single view that forgets `.visible_to()` is a privacy leak rather than a
cosmetic bug**. "Everyone remembers" is not a design.

One row per authenticated list URL — Feed · Home · post detail · profile · people search ·
post search · tag pages · role pages · comment lists · notification bell · conversation list ·
chat thread · Saved — each asserting a block-related user's content is **absent**, and each run
**in both directions** from a single one-way `Block` row. The asymmetry is the whole point: the
row is one-way, the effect is not, and a view that filters only `blocked` and not `blockers`
passes a naive test and leaks.

Then one test per row of the ADR-0002 table:

| Clause | Assertion |
|---|---|
| Profile | **404, not 403** — 403 confirms the account exists |
| Posts | absent from every list; direct URL 404s; both directions |
| Comments | hidden everywhere, not just on your own posts |
| DMs | send refused in both directions, no `Message` row |
| Existing chat | thread hidden from **both** inboxes · **`Message` and `Conversation` row counts are unchanged** · unblock restores it, same message bodies, same ids |
| Follows | both directions hard-deleted at block time · unblock does **not** restore them |
| Notifications | rows where the other party is `actor` deleted at block time |
| Saved posts | filtered from the Saved screen, `SavedPost` row **not** deleted |
| Counters | `comment_count` and `spark_count` are **identical** before and after blocking — global, never viewer-relative (ADR-0002) |
| Anonymous | logged out, the blocked user's public content is **still visible**. This is deliberate (ADR-0002 "soft barrier"), so it is pinned as an assertion — otherwise someone "fixes" it later with a login wall and destroys the product |

Plus the two orderings that break naive implementations: a block created **after** an existing
conversation, and a block created **after** an existing mutual follow.

The row-count assertions in the chat clause are load-bearing. ADR-0002 says hiding is a filter
and there must be **no delete path anywhere**; a `Message.objects.filter(...).delete()` written
in Phase 6 would satisfy every "the thread is hidden" test and quietly destroy the other
person's data. Counting rows is what catches it.

### 5.5 `test_query_budgets.py` — N+1, caught by invariance not by a magic number

The usual `assert_num_queries(12)` is brittle: it breaks on every unrelated change and gets
bumped until it means nothing. Better test:

```python
def test_feed_query_count_is_independent_of_page_size(client, django_assert_num_queries):
    seed_posts(5)
    with django_assert_num_queries() as small:
        client.get("/feed/")
    Post.objects.all().delete()
    seed_posts(25)
    with django_assert_num_queries() as large:
        client.get("/feed/")
    assert len(large) == len(small)      # 5× the rows, same number of queries
```

**A count that grows with the row count is the definition of N+1.** This assertion says that
and nothing else, so it doesn't need maintaining. Applied to: feed, home, post detail with
comments, search results, notification bell dropdown, conversation list.

Two specific claims from the schema get pinned here, because both were chosen *for*
performance and neither is self-proving:

- **The bell dropdown.** `data-model.md` §5.1 chose concrete nullable FKs over a
  `GenericForeignKey` specifically so it could be `select_related`. This test proves the choice
  was actually taken advantage of.
- **The block filter is one lookup per request, not per view.** ADR-0003 caches the set on the
  request object. A feed page that calls `blocked_user_ids()` six times must still issue one
  cache read — asserted with a spy, and revisited if ADR-0002's "revisit if" trigger fires.

---

## 6. The five things my brief says to always test

Written out so they can't be quietly skipped. **All five are now unblocked** — v1 had two of
them waiting on Jeni.

**Permissions** → §5.2, and every seat's own views.

**Empty states** → every list screen gets a test at zero rows: feed with no posts, profile
with no posts, search with no results, notifications empty, messages empty, saved empty,
comments empty. Each asserts 200 (not 500, not a blank page) and that the empty-state copy
renders. Designer owns the copy; QA owns proving it appears. Empty states are the most-skipped
and most-seen-by-strangers screens in any portfolio project.

**Brand-new user, zero follows** → the Home cascade (`product-spec.md` §4.3) gets one test per
tier, each constructed to force that tier:

1. follows + interests present → posts from those
2. no follows, has a `field_tag` → **most-sparked posts carrying that tag, last 7 days**
3. nothing at all → newest posts overall
4. **the guarantee:** a user with zero follows, zero interests, no field, on a database with
   ≥1 *visible* post, gets a non-empty Home.

**Tier 2 is asserted specifically, not by proxy.** ADR-0004 requires it: the `Tag.kind` bug
made tier 2 return zero rows forever, and the cascade hid that by falling through to tier 3
with Home still looking full. So the test asserts *which tier filled the page*, and the tier-2
posts are constructed so tier 3 would have returned different rows. This needs the view to say
which tier it used — §10 Q-C, a small ask to Discovery.

The word "visible" in the guarantee is doing real work, and it is why the guarantee as written
in the spec is **not yet testable** (§10 Q-B): a database with exactly one post that is
soft-deleted, or `team_formed`, or authored by someone the viewer has blocked, yields an empty
Home no matter how good the cascade is. The honest guarantee is over posts that are
`deleted_at IS NULL`, `status='looking'`, and not block-filtered. Each of those three gets its
own edge test asserting the **empty state renders, not a 500**.

**Blocked-user behaviour** → §5.4, in full. Unblocked by ADR-0002.

**Rate limits** → the Nth request succeeds, the N+1th is refused, and the counter is per-user
or per-IP as configured, not global (a global limiter locks out every user the moment one
spammer hits it — an easy and severe bug). Rate limits are disabled by default in tests via the
autouse `no_rate_limits` fixture, enabled explicitly in the tests that assert them; otherwise
every other seat's suite starts failing at request 11 for reasons nobody can find. The limiter
state is in Redis, so `clear_cache` runs between these tests or the second one starts already
throttled.

**Irreversible actions** → delete post, delete comment, delete account, block. Each: only the
owner can, it requires POST (never a GET — a `GET /post/x/delete/` is followed by every link
prefetcher and crawler that touches the page), it is confirmed, and the correct rows survive.

**Account deletion (ADR-0001), unblocked, one test per clause:**

- requesting deletion sets `deletion_requested_at` and nothing else is scrubbed yet
- logging in during the window cancels it — field back to null, profile untouched
- the job at **day 29 does nothing**; at **day 31** it scrubs. Both asserted with freezegun
- after the scrub: `is_active=False`, password unusable, email is a **non-colliding**
  placeholder (create a second deleted account and assert no `IntegrityError`), every listed
  `Profile` field cleared, interests and skills gone
- posts, comments and messages **survive**, and every surface renders `[deleted]` without
  crashing — post card, comment, conversation header, notification
- follows, blocks, sparks, saves and actor-notifications are **hard-deleted**
- **a `Report` naming the user as its subject survives** — this is the abuse path ADR-0001
  exists to close, so it is asserted directly
- **the job is idempotent** — running it twice leaves the same row. Currently *not* assertable;
  see §10 Q-A, my one blocking schema request

---

## 7. The seed data command

`product-spec.md` §5 calls this critical, and it is: it is the first and possibly only thing a
stranger sees. My brief ranks it equal to a feature. Treating it that way.

```bash
python manage.py seed_demo [--users 20] [--posts 45] [--seed 20260731]
                           [--reset] [--yes] [--quiet]
```

### 7.1 The one decision that decides whether this works

**Faker generates names, cities, dates, and handles. It does not generate the ideas.**

`Faker.text()` produces "Lorem ipsum dolor sit amet" or, worse, plausible-looking sentence
salad. A visitor reads two post bodies and knows instantly the site is fake, and that
impression is unrecoverable — it lands before they've seen a single feature.

So the seed ships with a **hand-authored corpus** of ~60 real idea posts, in
`<app>/management/commands/_seed_corpus.py`: a title, a 60–200 word body in a real human
voice, its tags, its roles-needed, its stage and commitment level. Written across the fields
`product-spec.md` actually targets:

software · hardware/IoT · **craft & small business (the crochet case — §1 names it, so it must
appear)** · food · campus & civic · fintech · edtech · climate · content/media · fitness

Bodies vary in length and polish — some are three tidy paragraphs, some are one excited
run-on. Real communities are not uniformly well-written, and uniformity is what reads as
synthetic.

Same for people: ~20 hand-written bios and headlines matched to plausible Indian and
international names, occupations and skills, so a profile page reads like a person.

**Roles in the corpus come from the curated `Role` list** seeded by `posts` 0002, not from
free text (ADR-0004) — otherwise the role filter has nothing to match and Discovery's filter
tests have no data. Each post also gets 0–2 free-text `custom_roles` on about a fifth of the
corpus, so the "Other" path is visible in the demo and searchable.

**Post tags draw from a pool that includes the ~15 curated field tags.** ADR-0004 action item 6
requires it: if no post carries a curated field tag, Home tier 2 returns nothing on the
deployed site and the bug ADR-0004 fixed reappears as a data problem instead of a schema one.
See §7.2 for the hard invariant this creates.

**This corpus is content, not code.** I'll draft it; Jeni edits anything that doesn't sound
right. It's the part of the demo her taste matters most on.

### 7.2 Distributions, not uniform randomness — plus three hard invariants

A real community is lumpy. Uniform random data feels wrong in a way people notice but can't
name.

| Thing | Shape |
|---|---|
| Posts per user | Power-law: 2 users post 5–7, most post 1–3, 3 users post 0 |
| Sparks per post | Heavy-tailed: 2 posts at 40–60, most at 0–8, **~8 posts at 0** |
| Comments per post | ~15% of posts have **zero comments** — the empty state must be visible in the live demo |
| Followers | A few well-followed users, most with 1–4 |
| Post dates | Spread over ~90 days, weighted toward the last 2 weeks |
| Status | ~4 `team_formed`, ~2 `closed`, rest `looking` |
| Staleness | 2–3 posts old and untouched, so the nudge job has something real to act on |

**Timestamps are a trap.** `auto_now_add` stamps everything "now"; a feed where all 45 posts
say "2 minutes ago" is more obviously fake than lorem ipsum. `data-model.md` §2.3.1 gives us
`published_at` as a writable ordering key precisely for this. The command sets dates explicitly
and enforces the ordering invariants: comments after their post's `published_at`,
`last_activity_at` ≥ latest child activity, sparks after the post existed, nothing in the
future. There is a test for exactly this (§7.6).

Three things are **guaranteed, not sampled.** Randomness that *usually* produces them is not
good enough, because the one run that doesn't is the deployed one:

1. **Tier 2 must be demonstrable.** For every curated field tag assigned to a demo account
   (§7.5), the seed guarantees **≥3 posts carrying that tag, published within the last 7 days,
   with non-zero sparks**. Sampled from a 90-day spread across ~15 tags, the expected count is
   well under one — so `demo.new@`, whose entire purpose is showing the cold-start experience,
   would fall straight through to tier 3 and the personalisation would be invisible on the
   live site. This is the single most likely way the demo silently under-sells the star
   feature.
2. **Every empty state is reachable.** ≥1 post with zero comments, ≥1 with zero sparks, ≥1
   user with zero posts, ≥1 user with zero followers.
3. **Every filter returns rows.** At least one post for each `stage`, each `commitment`, ≥3
   distinct `city_slug`s with ≥2 posts each, and ≥5 curated roles used across the corpus.
   A filter dropdown that returns "no results" for half its options reads as broken.

### 7.3 Counters and derived columns come from real rows

Sparks, comments, follows and saves are created as **real rows**, then all denormalised
counters are recomputed in one aggregate pass at the end — by calling the same reconciliation
task `data-model.md` §7.4 specifies.

Two benefits: the seed can never ship counters that disagree with reality, and running the
seed exercises the reconciliation task for free, every time.

**The same applies to `search_vector` and `keywords`, and this is the seed's most likely
silent failure.** `bulk_create` does not fire `post_save`, so anything created in bulk has a
null `search_vector` — which means **search returns nothing on the deployed site** while every
unit test of the extractor passes. §7.8 uses `bulk_create` for speed, so the seed ends with an
explicit recompute pass over posts and profiles, and §7.6 asserts no seeded row has a null
vector. The star feature failing on the demo because of a bulk insert is not a hypothetical;
it is the default outcome if nobody writes this down.

### 7.4 Safety — this is a destructive command

It writes ~5,000 rows and `--reset` deletes. Guard rails:

1. **`is_demo=True` on every seeded user**, including the three public demo accounts. `--reset`
   deletes only rows attributable to `is_demo` users. It is never a `flush`, never a
   `TRUNCATE`. `is_public_demo` has **nothing to do with `--reset`** — see §7.5.
2. **Refuses to run if the database contains non-demo users**, unless `--yes` is passed
   explicitly. That check is what stops it being run against production data that isn't
   demo data.
3. **Idempotent.** `get_or_create` on username, and on **`(author, title)` for posts** — *not*
   on slug. `Post.slug` is `slugify(title)` + a **random suffix** (`data-model.md` §2.3), so
   the seed cannot know the slug of a row it hasn't created yet and slug-keyed get-or-create
   would create a second copy of all 45 posts on the second run. `(author, title)` is a natural
   key the seed fully controls. Asserted by the idempotency test in §7.6, which is the test
   that would have caught this.
4. **`--reset` leaves the database consistent, not merely smaller.** Deleting demo users
   cascades through their posts and comments but leaves `Tag` rows behind with stale
   `post_count` values — a tag cloud reading "fintech (12)" over zero posts. So `--reset`
   finishes by running the reconciliation task and deleting non-curated tags that end at
   `post_count=0`. **Curated tags and roles from the `posts` 0002 data migration are never
   deleted** — `Profile.field_tag` and the onboarding picker depend on them existing
   identically in every environment.
5. **Never runs automatically on deploy.** Not in `start-web.sh`, not in a release hook. It is
   a documented manual step in the README, run once.
6. **Refuses in prod without `--yes`,** and logs a one-line summary of what it created.

### 7.5 The demo accounts — and the two flags

`product-spec.md` §5.3 wants credentials on the login screen. That needs three accounts, not
one:

| Account | `is_demo` | `is_public_demo` | State |
|---|---|---|---|
| `demo@alongside.app` | ✅ | ✅ | Curated: 3 posts, follows 6 people, 2 conversations with unread messages, 4 unread notifications, 5 saved posts, a curated `field_tag` |
| `demo.new@alongside.app` | ✅ | ✅ | Brand new: no follows, no interests, no posts. A `field_tag` **is** set, so tier 2 is what a visitor sees (§7.2 invariant 1) |
| `demo.mod@alongside.app` | ✅ | ✅ | Staff, for the moderation queue. Seeded with 2 open reports so the queue isn't empty. **Sharply restricted — see below** |
| the other ~17 seeded users | ✅ | ❌ | Authors of everything that makes the site look alive |

**The two flags do different jobs and the tests must not confuse them** (`data-model.md`
§1.1.1):

- **`is_demo`** = data lineage. "This row came from `seed_demo`, so `--reset` may delete it."
  True for all ~20 users. **It carries no permission meaning at all.** v1 of this document
  enforced the write-block off `is_demo`, which would have made all 17 content-authoring
  seeded users unable to own posts — an empty-looking site, which is the exact failure the
  seed exists to prevent. Corrected here.
- **`is_public_demo`** = write restriction. "This account's password is printed on a public web
  page." True for three accounts. Browse, spark and save succeed; **post, comment and DM
  return 403 and create no row.**

Two consequences that matter:

- **The restriction lives at the request layer, never in `Model.save()` or a signal.** The
  demo account's rich state — 3 posts, 2 conversations, sent messages — is written *by the
  seed command*, which must not be blocked by it. If the Accounts seat enforces this in a model
  save or a pre_save signal, the seed cannot build the state and §7.5 collapses into an empty
  demo account. **Note for the Accounts seat, via Jeni:** view/form/service layer only.
- **Attempting a blocked action says so plainly** — "The demo account can browse and spark —
  sign up to post" — rather than failing silently. Designer owns the copy.

**🔴 `demo.mod@` is a published staff password, and that is a bigger hole than the write-block
closes.** `is_public_demo` is an application-layer check; **Django admin does not consult it**.
As specified, anyone reading the login screen can open `/admin/`, delete every row in the
database, and change other users' passwords. The write-block does nothing about it.

My recommendation, and a change request to the Architect and Trust & Safety via Jeni: seed a
`demo_moderator` **Group** carrying exactly `moderation.view_report` and
`moderation.change_report`, assign `demo.mod@` to it, and grant nothing else. Then:

- `is_superuser` is **False**, asserted
- the account holds **no `delete_*` permission on any model**, asserted by iterating every
  installed model rather than a hand-written list, so a new app can't quietly widen it
- `/admin/accounts/user/` returns 403 for it, asserted
- it can open the report queue and change a report's status, asserted (otherwise the demo is
  pointless)

If Jeni would rather not publish a staff password at all, the alternative is to drop
`demo.mod@` from the login screen and show the queue in README screenshots. Either answer is
fine; the current specification is not.

### 7.6 The seed command gets its own tests

It runs at Phase 7 (Day 42 — the last day). A seed that quietly broke in Phase 4 and is
discovered on the final afternoon is the worst possible timing, so it is tested from the day
it is written, in `tests/cross/test_seed_demo.py`:

- runs to completion with `--users 3 --posts 5`
- **idempotent** — run twice, counts unchanged (the test that catches the slug problem, §7.4.3)
- every created user has `is_demo=True`; exactly three have `is_public_demo=True`; **no user
  has `is_public_demo` without `is_demo`** — one that did would survive `--reset` and leave
  published credentials pointing at an account whose data is gone
- `--reset` deletes demo rows and leaves a non-demo user untouched
- `--reset` leaves **no stale counters and no orphans**: curated tags and roles still present,
  non-curated tags at `post_count=0` gone, every remaining `Tag.post_count` equal to a real
  count
- refuses without `--yes` when non-demo users exist
- counters equal real row counts
- **no seeded `Post` or `Profile` has a null `search_vector`** (§7.3)
- date invariants hold — no comment predates its post, `last_activity_at ≥ published_at`,
  nothing in the future
- no post body is empty, no user has an `example.com`-shaped throwaway email, no username
  matches `^(test|user|asdf)\d*$`
- the three §7.2 guarantees hold: tier-2 data exists for every demo account's `field_tag`;
  every empty state is reachable; every filter option returns rows
- `demo.mod@` has no delete permissions and is not a superuser (§7.5)

### 7.7 Avatars — resolved ✅

**Unblocked by the Architect, 31 Jul (`data-model.md` §1.2.1).** `Profile` now carries a plain
`avatar_url` alongside the `CloudinaryField`, and precedence lives in one property:

```python
profile.avatar_display_url   # upload → avatar_url → DEFAULT_AVATAR
```

The seed sets `avatar_url` to a deterministic illustrated avatar derived from the username. A
real upload always wins. Seats call `avatar_display_url` and never branch themselves — which is
also why it gets a unit test rather than being trusted (§2.1), including the case that matters
most in a demo: **both fields blank must still return something renderable, never `""`**. An
empty `src` renders as a broken-image icon on every card on the page.

**One risk worth naming, and it is mine to raise because it lands on the first impression.** If
`avatar_url` points at a third-party avatar service, then twenty broken images appear the day
that service rate-limits us, changes its URL scheme, or goes down — and it is an external
request per avatar per page view for every visitor. Deterministic does not mean dependable.

Recommendation: generate the ~20 avatar SVGs **once**, commit them under
`static/demo/avatars/<username>.svg`, and point `avatar_url` at our own static URL. Still
deterministic, still free, no runtime third-party dependency, and WhiteNoise already serves it
(`deployment.md`). ~40 KB in the repo. Flagged to the Architect as §10 Q-F — it needs no schema
change either way, so it does not block the migration.

**Post images have the same problem and no solution yet — §10 Q-E.** `PostImage.image` is a
`CloudinaryField` with no URL sibling, so the seed cannot attach images to posts by the route
that was just approved for avatars. A 45-post demo of pure text reads thinner than it should,
and the crochet case — the one `product-spec.md` §1 names — is inherently visual.

### 7.8 Performance

Target: **under 60 seconds locally**, and it must survive being run against Neon from a laptop
in Bangalore — every round trip crosses the internet, so ~5,000 individual `INSERT`s would take
minutes. `bulk_create` for sparks, follows, tags and comments; individual saves only where a
signal has to fire — and an explicit recompute pass at the end for everything the bulk path
skipped (§7.3).

One production note: `deployment.md` §4 runs Render's free tier with
`CELERY_TASK_ALWAYS_EAGER=True`, so the search-vector task runs **inline**. Against a remote
database that is one extra round trip per post at seed time. It is fine at 45 posts; it is
worth knowing before anyone raises `--posts` to 500.

---

## 8. Cross-device — 375px, and an objective assertion

Not pytest's job. This is browser work, done per phase, with a fixed matrix.

| Width | Stands for |
|---|---|
| **375 × 812** | The one that matters — mid-range Android, the primary user |
| 768 | Tablet / large phone landscape |
| 1280 | Desktop |

**The one mechanical check, run on every screen at 375px:**

```js
document.documentElement.scrollWidth <= window.innerWidth
```

Horizontal scroll is the single most common mobile failure and it is completely objective — no
taste required, no screenshot needed. Every screen, every phase.

Also checked at 375px, by hand: tap targets ≥ 44px · no text under 14px · modals and drawers
scroll internally rather than clipping · long words and URLs wrap · a 140-char post title
doesn't break the card · the chat input isn't hidden by the mobile keyboard · a `[deleted]`
author and a missing avatar don't collapse a card's layout.

Recorded per phase as a pass/fail table in the QA report. Anything visual and subjective goes
to Jeni with a screenshot — I check for breakage, she judges whether it looks right.

---

## 9. Tooling, config, and one dependency request

**Config** in `pyproject.toml` (`[tool.pytest.ini_options]`), not a separate `pytest.ini` —
one fewer file, and Ruff already lives there. **Already landed** with the Architect's skeleton;
the `[tool.pytest.ini_options]` and `[tool.coverage]` sections are QA's to change.

```
DJANGO_SETTINGS_MODULE = "config.settings.dev"
addopts = "--strict-markers --reuse-db"
testpaths = ["tests"]
```

`--reuse-db` locally for speed; CI always uses a fresh database, so migrations run start to
finish on every push. `--strict-markers` so a typo'd marker fails instead of silently skipping.

**Markers:** `slow` (excluded from the fast local run), `browser` (device checks, not run in
CI).

**One settings requirement:** the test settings set `CELERY_TASK_ALWAYS_EAGER=True`. Search
vectors are populated by a Celery task (`data-model.md` §3); without eager mode every search
test fails with an empty result set and the cause is invisible. Production already runs eager
on the free tier, so this also matches prod.

**Coverage.** No gate until Phase 2 — gating an empty project just blocks the build. From
Phase 2: `--cov-fail-under` set to the current number and ratcheted upward, never down. Target
~85% overall, but the number is not the goal: **permissions, block visibility, the Home
cascade, search, and messaging are held to ~95%**, and I'd rather have 70% coverage with a real
permission matrix than 95% with none. Coverage measures which lines ran, not whether anything
was verified.

**One dependency request for DevOps (via Jeni): `freezegun~=1.5` in `requirements/dev.txt`.**
Five features are time-dependent — the 30-day stale-post nudge, the **30-day deletion grace
window**, the 60-second notification dedup, the 5-minute `last_seen_at` throttle, and "top
posts in your field *this week*". The alternative is patching `timezone.now` by hand in every
test, which is noisier and easy to get subtly wrong. Small, standard, dev-only.

---

## 10. What I need — v2

v1's list had eight open items. **Six are answered** (Q1 deletion, Q2 roles, Q3 comment sparks,
Q4 staleness, Q5 block, Q9 spark notifications, Q12 avatars — recorded in `data-model.md` §9
and the four ADRs). What follows is the new list, from reviewing the approved schema for
testability. Ranked by what it blocks.

**Q-A · `User` needs an `anonymised_at` field.** 🔴 *Architect — before the migration is
locked.*
ADR-0001 requires the scrub to be idempotent, and §6 requires me to prove it. There is no
field that says it happened. Today the state is inferred from `deletion_requested_at IS NOT
NULL AND is_active = False`, and that inference is wrong in two reproducible ways: a user who
requests deletion and is then **banned** by moderation (which also sets `is_active=False`,
`data-model.md` §1.1) starts rendering as `[deleted]` everywhere while their bio and avatar are
still on screen; and a scrub job that **crashes halfway** through clearing twelve profile
fields leaves a row that no longer matches its own selection query, so it is never retried and
stays half-anonymised forever. One nullable indexed datetime fixes both, makes the job's query
honest (`deletion_requested_at <= now-30d AND anonymised_at IS NULL`), makes `User.name` a
single-field check, and turns the idempotency test into two lines. Cheapest possible fix, and
it has to happen before `accounts` 0001 is locked or it costs a migration on the auth table.

**Q-B · Is the Home guarantee over *all* posts or *visible* posts?** 🔴 *Jeni + Discovery.*
"Home is never empty for a brand-new user" is not testable as written. Three sub-questions,
each changing the assertion:
1. **Union or fallback?** If tier 1 returns 3 posts and the page wants 20, does Home show 3, or
   3 + 17 from tier 2? *My recommendation: top up to a target N, tiers in order, deduped.* A
   pure fallback means a user with one follow sees a one-post Home forever, which is worse than
   the cold-start case the cascade was built for.
2. **What is N?** Without a number there is no boundary to test. *Recommendation: 20.*
3. **What counts as a post?** A database with exactly one post that is soft-deleted, or
   `team_formed`, or authored by a blocked user, gives an empty Home no matter what. *My
   recommendation: the guarantee is over `deleted_at IS NULL AND status='looking'` and
   block-filtered posts, and the zero-visible-posts case renders the empty state — asserted as
   a 200, not a 500.*

**Q-C · Home should report which tier filled the page.** 🟠 *Discovery.*
ADR-0004 requires me to assert tier 2 *specifically* returns rows. Two tiers returning
overlapping posts are indistinguishable in a rendered response, so proving it from the outside
means constructing data where tier 3 would return different rows — fragile, and it proves the
rows appeared rather than that tier 2 ran. A `home_tier` value in the template context makes
the assertion direct, and doubles as a debugging aid on the live site. Small ask, large payoff.

**Q-D · `Notification` needs a `kind`-vs-target check constraint.** 🟠 *Architect.*
`Report` got "exactly one of three targets is non-null" as a `CheckConstraint`, and
`Notification` — which has the same shape and is rendered on **every page load** — got nothing.
The schema currently permits `kind='new_comment'` with `comment=NULL` and `kind='new_message'`
with `conversation=NULL`. Both render a bell entry linking nowhere, or crash the dropdown
template, and they'd surface during a demo rather than in a test. One `CheckConstraint` with
three OR'd `Q` clauses. Same reasoning that was already accepted for `Report`.

**Q-E · Post images in the seed — `PostImage` has no `image_url`.** 🟠 *Architect.*
Exactly the problem `avatar_url` was added to solve (`data-model.md` §1.2.1), one model over.
The seed cannot attach images to posts: uploading to Cloudinary from the command is slow,
credential-dependent and not idempotent — the reasons already rejected for avatars. Options:
(a) ship a text-only demo and never exercise the image path on the live site; (b) mirror the
avatar fix with a nullable `PostImage.image_url` + a `display_url` property; (c) upload at seed
time. *Recommendation: (b), pointing at ~5 committed static images used across ~8 posts.*
Symmetric with a decision already made, one nullable field, and the crochet post — the one the
spec names — gets to have a picture.

**Q-F · Where do the seeded avatar URLs point?** 🟡 *Architect, my recommendation in §7.7.*
Committed static SVGs rather than a third-party avatar API. No schema impact, so it does not
block the migration; it does decide whether the demo has twenty broken images the day an
external service changes.

**Q-G · Conversation creation needs one owner.** 🟡 *Architect / Messaging.*
`dyad_key` is unique, but nothing ties it to the actual `ConversationParticipant` rows: the
schema permits `dyad_key='3:7'` on a conversation whose participants are 3 and 9, after which
get-or-create for (3,7) hands user 7 a thread they are not in. It is cross-table, so it is not
cheaply constrainable — which is the argument for a single
`Conversation.objects.get_or_create_dyad(a, b)` helper that writes the key and both
participants in one transaction, so the invariant has one owner and one test instead of living
in whichever view calls it. Same shape as the `visible_to()` decision in ADR-0003.

**Q-H · `demo.mod@` publishes a staff password.** 🔴 *Jeni — product call.*
§7.5. `is_public_demo` is an application check and Django admin ignores it entirely, so as
specified, anyone can open `/admin/` from the login screen and delete the database. Either
lock it to a `demo_moderator` group with view/change on `Report` and nothing else, or don't
publish that account. This one is not a testing question — I can test either answer; I can't
test the absence of a decision.

**Q-I · Should `last_activity_at ≥ published_at` be a DB check?** 🟡 *Architect, low priority.*
It is expressible as a `CheckConstraint` with `F()`, it is an invariant the stale job and the
feed ranking both assume, and it would make a seed bug fail loudly instead of producing posts
whose "last activity" predates their existence. Cheap; say no if you'd rather not carry it.

---

## 11. What I'm doing next

The skeleton has landed, so this is a work list. In order, and none of it needs a feature to
exist:

1. **Absorb `tests/test_skeleton.py`** — the Architect wrote it so CI wouldn't go red on an
   empty `tests/`, and handed it over. It already covers items 2 and 3 of v1's list (healthz
   without a database, `AUTH_USER_MODEL`, `User` alone in 0001). Keeping all four tests,
   extending them.
2. `tests/conftest.py` — Faker seeding, the fixtures in §4.2, `no_rate_limits` and
   `clear_cache` autouse.
3. A migration test: the full chain applies to an empty database, and `pg_trgm` and `unaccent`
   actually exist afterwards. Extensions created in a migration is the plan (`data-model.md`
   §3); this proves it happened rather than someone having created them by hand locally.
4. Factories for `User` and `Profile` the moment `accounts` 0002 lands — with the trait names
   in §4.1 rule 4, so no test ever writes `demo=True` again.
5. `test_constraints.py`, growing with each migration. It can start now: `User.username`,
   `User.email` and the reserved-name validator are all in 0001 already.
6. The seed corpus draft, in parallel — it's writing, not coding, so it doesn't block on code.
   ~60 posts and 20 bios, mine to draft, Jeni's to cut and rewrite before it ships.
