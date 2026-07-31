# Alongside — Data Model (v1)

> **Alongside** — nobody builds alone.

**Status:** ✅ **APPROVED by Jeni, 31 Jul 2026. This is the contract — build against it.**
**Author:** Architect · **Written:** 30 Jul 2026 · **Approved:** 31 Jul 2026
**Companion to:** `product-spec.md` (requirements), `tech-stack.md`, `roadmap.md`, `adr/`

This file is the contract between all ten seats. Any change to a model or field goes through
the Architect via Jeni, and lands **here** before it lands in a migration.

**Decisions with real trade-offs are recorded as ADRs** in `docs/adr/`. Where this document
says "see ADR-000X", that ADR is the reasoning and this is the summary.

| ADR | Decision |
|---|---|
| [ADR-0001](adr/0001-account-deletion-anonymise.md) | Account deletion anonymises; 30-day grace window |
| [ADR-0002](adr/0002-block-is-mutual-invisibility.md) | Block is full mutual invisibility; chat hidden not deleted |
| [ADR-0003](adr/0003-block-filter-strategy.md) | Block enforcement: cached id set + `visible_to()` |
| [ADR-0004](adr/0004-one-tag-vocabulary.md) | One tag vocabulary; roles curated + free-text "Other" |

---

## 0. How to read this

- Every model lists: fields → relationships → indexes/constraints → why.
- `→` marks a foreign key. `⇄` marks many-to-many.
- **§9 records the eleven questions the spec left open and the answers Jeni gave.** Read it —
  several of them changed the schema.

### Conventions applied everywhere

| Convention | Decision |
|---|---|
| Primary keys | `BigAutoField` (Django 5.2 default). Public URLs use `username` / post `slug`, never the raw id |
| Timestamps | `created_at = auto_now_add`, `updated_at = auto_now` on anything editable |
| Time | Store UTC (`USE_TZ = True`), render in the viewer's locale |
| Text | `CharField` for bounded, `TextField` for freeform. No `null=True` on text — use `""` |
| Deletes | Explicit `on_delete` on **every** FK — see §8 |
| Counters | Denormalized `*_count` columns, written with `F()` expressions — see §7 |
| Visibility | Authenticated list queries call `.visible_to(user)` — see §1.6 |
| App ownership | Model lives in the app that owns its lifecycle (per `tech-stack.md` §13) |

> **`TextField(500)` is not a database limit.** Django's `TextField` accepts `max_length` but
> enforces it **only in forms**, never in Postgres. Where this document writes `TextField(N)`,
> read it as "N enforced at the form layer". If a limit must hold at the database level it is
> written as `CharField(N)` or carries an explicit `CheckConstraint`. This matters to QA: a
> test that posts a 5000-character body through the ORM will succeed.

---

## 1. `accounts` — identity, profile, graph edges

### 1.1 `User` (AUTH_USER_MODEL — **must be in migration 0001**)

Subclasses `AbstractUser`. Kept deliberately thin: this table is the hardest one in Django to
change later, so only identity and auth live here. Everything that churns lives on `Profile`.

| Field | Type | Notes |
|---|---|---|
| `id` | BigAuto | |
| `username` | CharField(30), unique, indexed | Public handle, used in URLs (`/u/<username>`). Validator `[a-z0-9_]{3,30}`, lowercased on save, reserved-name blocklist (`admin`, `api`, `feed`, `login`, …) |
| `email` | EmailField, **unique**, indexed | allauth logs in by email; unique is not Django's default — we override |
| `display_name` | CharField(60), blank | What renders on cards. Falls back to `username` |
| `password` | inherited | Django PBKDF2 |
| `is_active` / `is_staff` / `is_superuser` | inherited | `is_active=False` = deactivated, banned, or deleted (§8) |
| `date_joined` | inherited | |
| `last_seen_at` | DateTimeField, null | Updated at most once/5 min by middleware. Cheap now; Phase 2's "usually replies within a day" needs it |
| `is_demo` | BooleanField, default False | **Seed-data marker.** Every user created by `seed_demo` has it. `--reset` deletes only these rows |
| `is_public_demo` | BooleanField, default False | **Write restriction.** The three accounts whose credentials are published on the login screen. Cannot post, comment or DM — see §1.1.1 |
| `deletion_requested_at` | DateTimeField, null, indexed | Start of the 30-day grace window (ADR-0001). Null = not deleting |

- `first_name` / `last_name` are set to `None` — we use `display_name`.
- **Not** on User: bio, avatar, links, onboarding answers, counters → all on `Profile`.

#### 1.1.1 Why `is_demo` and `is_public_demo` are two fields

They answer different questions and the seed relies on both:

- **`is_demo`** = "this row came from `seed_demo`, so `--reset` may delete it." True for all
  ~20 seeded users. It is a *data lineage* marker.
- **`is_public_demo`** = "this account's password is printed on a public web page, so it must
  not be able to write." True for the three accounts in `testing.md` §7.5 only.

Collapsing them into one flag breaks the seed: the other ~17 seeded users must be able to own
posts and comments (that is what makes the demo look alive), while `demo@alongside.app` must
not be able to add any. One flag would force a choice between a graffiti-able demo account and
an empty-looking site.

**Enforcement is a real permission check** owned by the Accounts seat — `is_public_demo` users
get 403 on create-post, comment and send-message, and success on spark and save. A hidden
button is not a permission. QA covers it as the sixth actor in the permission matrix.

### 1.2 `Profile` (1:1 → User, `on_delete=CASCADE`)

Created in the same transaction as the user (`post_save` signal, `get_or_create`). Every query
that renders a user uses `select_related("profile")`.

| Field | Type | Notes |
|---|---|---|
| `user` | OneToOne → User, primary_key=True | PK = user_id, so no extra id column and joins are free |
| `avatar` | CloudinaryField, blank | Uploaded image. Never `ImageField` to local disk — Render's filesystem is ephemeral |
| `avatar_url` | URLField, blank | **Externally-hosted fallback avatar** — see §1.2.1 |
| `bio` | TextField(500), blank | |
| `headline` | CharField(120), blank | One-liner under the name on cards |
| `occupation` | CharField(120), blank | Onboarding step 2 — free text, for display |
| `field_tag` | FK → `Tag`, null, SET_NULL | Normalized field. Powers Home tier 2 (§4.3). **An ordinary topic tag** — ADR-0004 |
| `purpose` | CharField(10), choices, blank | `post` / `find` / `both` (onboarding step 1) |
| `city` | CharField(80), blank | Free text |
| `city_slug` | SlugField(80), blank, indexed | Auto-derived, normalized for filtering |
| `is_remote_friendly` | Boolean, default True | |
| `work_done` | TextField(1000), blank | "Work done so far" (spec §4.1) |
| `custom_skills` | ArrayField(CharField(50)), default list | Free-text skills not on the curated `Role` list. Max 3, searchable, **not** filterable — ADR-0004 |
| `github_url` / `portfolio_url` / `website_url` | URLField, blank | Three fixed fields (§9 Q7) |
| `onboarding_completed_at` | DateTimeField, null | Null = never finished. All steps skippable, so informational, not a gate |
| `follower_count` / `following_count` / `post_count` | PositiveIntegerField, default 0 | Denormalized, see §7 |
| `search_vector` | SearchVectorField, null | People search (spec §4.3 "posts *and* people") |
| `created_at` / `updated_at` | | |

**Relationships**
- `skills` ⇄ `Role` through `ProfileSkill` — "roles you can fill" (spec §4.1)
- `interests` ⇄ `Tag` through `ProfileInterest` — onboarding step 3, drives Home tier 1

**Indexes**
- `GinIndex(fields=["search_vector"])`
- `Index(fields=["city_slug"])`
- `Index(fields=["field_tag"])` — Home tier 2

#### 1.2.1 Why there are two avatar fields

`CloudinaryField` stores an asset owned by our Cloudinary account. Seeding 20 avatars would
mean uploading 20 images from the seed command — slow, credential-dependent, and not
idempotent, which breaks `testing.md` §7.4's requirement that the seed can run twice.

`avatar_url` holds an external URL instead. The seed sets it to a deterministic generated
avatar derived from the username (DiceBear-style illustrated, not photographic — synthetic
photorealistic faces on a site claiming a real community is a bad look, and real people's
photos are out of the question). Free, deterministic, zero bytes in the repo.

Precedence is fixed and belongs in one place, not in every template:

```python
@property
def avatar_display_url(self):
    return self.avatar.url if self.avatar else (self.avatar_url or DEFAULT_AVATAR)
```

An uploaded image always wins. Seats call `profile.avatar_display_url` and never branch
themselves. *(Unblocks `testing.md` §10 Q12.)*

### 1.3 `ProfileSkill` / `ProfileInterest` (explicit through-models)

Both are plain join tables with `created_at`, `UniqueConstraint(profile, role|tag)`, and an
index on the reverse side (`role_id` / `tag_id`) so "who can do X" and "who's interested in Y"
are indexed lookups. Explicit through-models cost nothing now and mean adding a field
(e.g. skill proficiency in Phase 2) isn't a table rebuild.

### 1.4 `Follow`

One-way, instant, no approval (spec §2.2, §4.4).

| Field | Type | Notes |
|---|---|---|
| `follower` | FK → User, CASCADE, related_name=`following_edges` | |
| `following` | FK → User, CASCADE, related_name=`follower_edges` | |
| `note` | CharField(200), blank | The optional follow note — e.g. "I'd want the backend role" |
| `created_at` | | |

**Constraints & indexes**
- `UniqueConstraint(follower, following)` — the whole idempotency story
- `CheckConstraint(~Q(follower=F("following")))` — no self-follow, enforced in the DB
- `Index(following, -created_at)` — "your followers, newest first"
- `Index(follower, -created_at)` — "who you follow", and the Home-feed join

> Follow rows in **both** directions are hard-deleted when either user blocks the other
> (ADR-0002). Unblocking does not restore them.

### 1.5 `Block` — full mutual invisibility

Lives in `accounts` (not `moderation`) because it is read on nearly every authenticated query
and belongs with the graph.

| Field | Type | Notes |
|---|---|---|
| `blocker` | FK → User, CASCADE, related_name=`blocks_made` | |
| `blocked` | FK → User, CASCADE, related_name=`blocks_received` | |
| `created_at` | | |

- `UniqueConstraint(blocker, blocked)`, `CheckConstraint(~Q(blocker=F("blocked")))`
- `Index(blocker)`, `Index(blocked)` — **both** directions are queried, because the effect is
  symmetric

**Semantics (ADR-0002, decided by Jeni 31 Jul).** The row is one-way; the effect is symmetric
and global. Two users are *block-related* if a row exists in **either** direction. For an
authenticated viewer:

| Surface | Behaviour |
|---|---|
| Profile | 404 both ways (not 403 — that confirms the account exists) |
| Posts | Excluded from Feed, Home, search, tag/role pages. Direct URL 404s. Both ways |
| Comments | Hidden **everywhere**, not just on your own posts. Both ways |
| DMs | Cannot be sent either way |
| Existing chat | **Hidden from both sides, never deleted. Unblocking restores it** |
| Follows | Both directions hard-deleted at block time |
| Notifications | Rows where the other user is `actor` deleted at block time |
| Saved posts | Filtered out of the Saved screen, not deleted |

Two things that are deliberate and must not be "fixed":

- **Counters stay global.** A post shows the same `comment_count` to everyone. A
  viewer-relative count would leak exactly how many comments the blocked person wrote. Full
  reasoning in ADR-0002.
- **Block is a soft barrier, not a security control.** The feed is public, so a blocked person
  can log out and read public content. That is an accepted consequence of public browsing
  (`CONTRIBUTING.md` rule 7), **not** a bug — and the wrong fix for it is a login wall, which would
  destroy the product. ADR-0002 spells this out.

### 1.6 The visibility convention — every seat must follow this

Block is symmetric and global, which means roughly a dozen read paths need filtering, owned by
six seats who cannot see each other's chats. So the filter is centralised (ADR-0003):

```python
Post.objects.visible_to(request.user)        # ✅ do this
Comment.objects.visible_to(request.user)
Conversation.objects.visible_to(request.user)
```

- **Anonymous users:** `visible_to()` is a no-op returning `self`. Zero queries, zero cost. The
  public feed path is untouched.
- **Never hand-write** `.exclude(author__in=…)`. One method name, used identically everywhere.
- **Moderation and admin use the unfiltered managers on purpose** — a moderator must see
  blocked content, or the queue is blind.

Architect ships this before any feature seat writes an authenticated list view. QA's
`tests/cross/test_block_visibility.py` enumerates every authenticated list URL and fails if one
forgets the filter — a view that leaks is caught by someone other than its author.

---

## 2. `posts` — the core object

### 2.1 `Tag` — one vocabulary (ADR-0004)

One shared vocabulary for post topics, profile interests, **and** profile fields. Same table on
purpose: the Home feed matches a user's interest tags and field tag against post tags, and that
only works if they are the same rows.

| Field | Type | Notes |
|---|---|---|
| `name` | CharField(40) | Display form, e.g. "Machine Learning" |
| `slug` | SlugField(40), unique, indexed | Canonical key, e.g. `machine-learning` |
| `is_curated` | Boolean, default False | ~15 seeded broad tags. **Only these appear in the onboarding field picker.** User-created tags surface in suggestions once used |
| `post_count` | PositiveIntegerField, default 0 | Powers "trending"-ish ordering and tag suggestions |
| `created_at` | | |

**Topic tags are user-created free text** ✅ *(Jeni, 31 Jul)* — tags are matched by search and
keyword, not exact-match filtering, so drift costs little and expressiveness is worth more.

> **There is no `kind` field.** An earlier draft partitioned tags into `topic` / `field`, which
> made "top posts in your field this week" structurally incapable of returning a row. ADR-0004
> has the full post-mortem. `is_curated` covers the display concern without partitioning the
> table.

### 2.2 `Role` — curated, because it is filtered

Separate from `Tag` because roles are a **different dimension with different behaviour**: a tag
describes what an idea is *about*; a role describes what a *person* does. Crucially, roles are
**exact-match filtered** and tags are not — so role vocabulary drift breaks a feature while tag
drift does not.

| Field | Type | Notes |
|---|---|---|
| `name` | CharField(50) | "Backend Developer", "Illustrator", "Marketer" |
| `slug` | SlugField(50), unique, indexed | |
| `category` | CharField(20), choices | `engineering` / `design` / `product` / `business` / `creative` / `other` — groups the role picker |
| `is_curated` | Boolean, default True | ~40 seeded in a data migration. Admin can add more |
| `usage_count` | PositiveIntegerField, default 0 | |

**Roles are a curated list plus an "Other" free-text box** ✅ *(Jeni, 31 Jul — option c)*. The
free text lives in `Post.custom_roles` / `Profile.custom_skills`, **is included in the search
vector**, and **never appears in the role filter**. So an unusual role is findable by search
without fragmenting the filter. ADR-0004 §"The 'Other' free-text role".

### 2.3 `Post`

| Field | Type | Notes |
|---|---|---|
| `author` | FK → User, CASCADE | Never fires via account deletion — that anonymises (§8) |
| `title` | CharField(140) | |
| `slug` | SlugField(160), unique, indexed | `slugify(title)` + short random suffix. Stable across edits (never regenerated) so links don't rot |
| `body` | TextField | Freeform, Reddit-style |
| `stage` | CharField(12), choices, indexed | `idea` / `building` / `launched` |
| `commitment` | CharField(10), choices, indexed | `casual` / `serious` |
| `city` | CharField(80), blank | Free text |
| `city_slug` | SlugField(80), blank, indexed | Auto-derived filterable form |
| `is_remote_friendly` | Boolean, default False | |
| `status` | CharField(12), choices, default `looking` | `looking` / `team_formed` / `closed` — **author-controlled only** |
| `is_stale` | Boolean, default False, indexed | **System-controlled**, set by the nudge job. Separate from `status` so the job never overwrites the author's choice |
| `nudged_at` | DateTimeField, null | Last "still looking?" nudge sent |
| `last_activity_at` | DateTimeField, indexed | Bumped by spark/comment/edit. Drives the stale job and recency ranking |
| `custom_roles` | ArrayField(CharField(50)), default list | Free-text "Other" roles. Max 3. Searchable, not filterable |
| `keywords` | ArrayField(CharField(40)), default list | Output of Discovery's keyword extraction |
| `search_vector` | SearchVectorField, null | `title` A · `keywords` + `custom_roles` B · `body` C |
| `spark_count` / `comment_count` / `save_count` | PositiveIntegerField, default 0 | See §7 |
| `published_at` | DateTimeField, indexed | See §2.3.1 |
| `created_at` / `updated_at` | | |
| `deleted_at` | DateTimeField, null, indexed | Soft delete — see §8 |

**Relationships**
- `tags` ⇄ `Tag` through `PostTag`
- `roles_needed` ⇄ `Role` through `PostRole`
- `images` ← `PostImage` (reverse FK), **max 5** ✅ *(Jeni, 31 Jul)*

> **There is no `view_count`.** The spec never asks for view counts, and it would be the only
> counter requiring a database write on every page load, including anonymous ones, on free-tier
> Postgres. Cut. Adding it later is a one-line migration.

#### 2.3.1 `published_at`, and why there are no drafts

**There are no drafts in v1.** The spec's post fields (§4.2) don't include one and the status
values are `looking` / `team_formed` / `closed`. A post is live when created.

So `published_at` is not "the moment it left draft" — it is a **plain, writable `DateTimeField`
defaulting to now**, kept separate from `created_at` for one concrete reason: `created_at` is
`auto_now_add` and therefore immutable, and **the seed command must set arbitrary dates**.
`testing.md` §7.2 calls this out — a demo feed where all 45 posts say "2 minutes ago" is more
obviously fake than lorem ipsum. `published_at` is the writable ordering key that makes a
realistic 90-day spread possible.

It is also the feed's sort key rather than `updated_at`, so editing a post never reshuffles the
feed.

#### 2.3.2 Indexes — the hottest table in the app

**Stale posts are ranked lower, never hidden** ✅ *(Jeni, 31 Jul)*. That decision changes these
indexes, so it is worth being explicit: the feed's partial index must **not** exclude
`is_stale=true` rows, or stale posts would vanish instead of sinking. `is_stale` becomes the
**leading sort column** instead of a filter condition.

Feed ordering is therefore `ORDER BY is_stale ASC, <sort key> DESC`, and the indexes match it
column for column:

| Index | Serves |
|---|---|
| `Index(is_stale, -published_at)` **partial**: `WHERE deleted_at IS NULL AND status='looking'` | Default Feed, newest first, stale sunk to the bottom |
| `Index(is_stale, -spark_count, -published_at)` partial, same condition | Feed "most sparked", stale sunk, tie-broken by recency for deterministic pagination |
| `GinIndex(search_vector)` | Full-text search |
| `GinIndex(keywords)` | Keyword matching for Home |
| `Index(author, -published_at)` | Profile → their posts |
| `Index(status, -published_at)` | Filtered views, admin |
| `Index(-last_activity_at)` | The stale-post nudge job |
| `Index(city_slug, -published_at)` / `(commitment, -published_at)` / `(stage, -published_at)` | Discovery filters |
| `GinIndex(title, gin_trgm_ops)` | Fuzzy title search |

The partial condition still excludes `team_formed` and `closed`, because spec §4.8 says those
"get posts out of the active feed" — that is the author's own choice, unlike staleness.

> **Note for the Discovery seat:** filtering by tag or role is a join through `PostTag` /
> `PostRole`. At v1 scale (thousands of posts) that is correct and fast. Do **not** denormalize
> `published_at` onto the join tables until a real `EXPLAIN` says to.

### 2.4 `PostTag` / `PostRole`

Explicit through-models. Each: FK to post (CASCADE), FK to tag/role (PROTECT — never let
deleting a tag silently strip posts), `created_at`, `UniqueConstraint(post, tag|role)`, and
`Index(tag|role, post)` for reverse lookup.

`PostRole` also carries `note = CharField(120), blank` — "React dev, ~5 hrs/week". Roles stay
informational (spec §2.3): **no** `is_filled`, no application state. That would turn
team-forming into a workflow, which the product explicitly refuses to be.

### 2.5 `PostImage`

| Field | Type | Notes |
|---|---|---|
| `post` | FK → Post, CASCADE, related_name=`images` | |
| `image` | CloudinaryField | |
| `caption` | CharField(140), blank | |
| `order` | PositiveSmallIntegerField, default 0 | |
| `created_at` | | |

- `Index(post, order)`. **Max 5 images** per post ✅, enforced in the form.

### 2.6 `Comment`

Flat in v1 (spec §4.4). **Not editable, but deletable** ✅ *(Jeni, 31 Jul)*.

| Field | Type | Notes |
|---|---|---|
| `post` | FK → Post, CASCADE, related_name=`comments` | |
| `author` | FK → User, CASCADE | |
| `body` | TextField(2000) | |
| `spark_count` | PositiveIntegerField, default 0 | |
| `created_at` / `updated_at` | | |
| `deleted_at` | DateTimeField, null | **Soft delete** — a deleted comment may still be attached to an open report |

- `Index(post, created_at)` partial `WHERE deleted_at IS NULL` — the comment list
- `Index(author, -created_at)`
- **No `is_edited` field** — comments cannot be edited, so there is nothing to flag. `updated_at`
  stays (it is free, and moderation redaction touches the row). If editing is ever added,
  `is_edited` comes back with it.
- **No `parent` field.** Nested threads are Phase 2; adding a nullable self-FK then is a
  one-line, zero-downtime migration. Not carrying speculative structure now.

**Deletion is the author's, soft, and decrements `comment_count`** — see §7.

### 2.7 `PostSpark` / `CommentSpark` — two models, not one

Comment sparks are **in v1** ✅ — spec §4.4 says the reaction is on "posts *and* comments".

Each model: `user` FK CASCADE, `post`/`comment` FK CASCADE, `created_at`,
`UniqueConstraint(user, target)`, `Index(target)`, `Index(user, -created_at)`.

**Why two concrete models instead of one generic (ContentType) Spark:** real FK integrity, no
`content_type_id + object_id` composite lookups, `UniqueConstraint` actually works, and counting
is a plain indexed count. A generic model buys flexibility we have no use for — there will never
be a third sparkable thing in v1. This is the single most common place junior Django projects
over-engineer; we're not doing it.

**Sparks do not generate notifications** ✅ — spec §4.6 lists exactly three triggers and sparks
is not among them. Deliberate: spark notifications are noise.

### 2.8 `SavedPost`

`user` FK CASCADE · `post` FK CASCADE · `created_at` · `UniqueConstraint(user, post)` ·
`Index(user, -created_at)` (the Saved screen).

---

## 3. `discovery` — no models

Discovery owns **query logic only**: keyword extraction, `SearchVector` population, filters, and
the cascading Home feed. Its inputs (`Post.search_vector`, `Post.keywords`, `Post.custom_roles`,
`Profile.search_vector`, `Profile.field_tag`, `ProfileInterest`) all live in the apps that own
those objects.

Two things the Architect provides so Discovery isn't blocked:

1. A migration enabling the Postgres extensions: `pg_trgm` and `unaccent` (via
   `TrigramExtension` / `UnaccentExtension` operations).
2. `search_vector` columns + GIN indexes, already listed above.
3. A data migration seeding ~15 **curated field tags** and ~40 **curated roles**. Home tier 2
   depends on those rows existing identically in every environment.

**Search vector refresh:** update on save via a Celery task, **not** a DB trigger — keeps the
logic in Python where it is testable. Note the production reality from `deployment.md` §4:
`CELERY_TASK_ALWAYS_EAGER=True` on Render's free tier, so in production this runs inline in the
request. It is a small amount of work and that is fine, but Discovery should know the task is
not actually asynchronous in prod.

**The Home cascade** (spec §4.3), now that ADR-0004 makes tier 2 real:

| Tier | Query |
|---|---|
| 1 | posts by people you follow **+** posts carrying your interest tags |
| 2 | not enough? most-sparked posts carrying your `field_tag`, last 7 days |
| 3 | still not enough? newest posts overall |

QA must assert **tier 2 specifically returns rows**, not merely that Home is non-empty — tier 3
would satisfy the weaker assertion while hiding exactly the bug ADR-0004 fixed.

---

## 4. `messaging`

### 4.1 `Conversation`

| Field | Type | Notes |
|---|---|---|
| `dyad_key` | CharField(40), **null**, unique, indexed | `"{min_id}:{max_id}"` of the two participants. **This is what stops duplicate conversations** when both people hit "message" at the same moment — a unique constraint instead of a get-or-create race. Nullable by design: null = future group chat |
| `last_message_at` | DateTimeField, null, indexed | Denormalized so the conversation list sorts without touching `Message` |
| `last_message_preview` | CharField(140), blank | Same reason — the list renders with zero joins |
| `created_at` | | |

1:1 only in v1. In Postgres, `NULL`s do not collide in a unique index, so nullable `dyad_key`
allows any number of future group conversations without a schema change.

### 4.2 `ConversationParticipant`

| Field | Type | Notes |
|---|---|---|
| `conversation` | FK → Conversation, CASCADE, related_name=`participants` | |
| `user` | FK → User, CASCADE | |
| `last_read_at` | DateTimeField, null | Per-user read state → unread badge |
| `is_archived` / `is_muted` | Boolean, default False | |
| `joined_at` | | |

- `UniqueConstraint(conversation, user)`
- `Index(user, is_archived)` — "my conversations"

**Why a participant model rather than `user_a` / `user_b` columns:** read state is per-user and
belongs on a per-user row; `user_a`/`user_b` forces `Q(a=me) | Q(b=me)` on every query and can't
index cleanly.

### 4.3 `Message`

| Field | Type | Notes |
|---|---|---|
| `conversation` | FK → Conversation, CASCADE, related_name=`messages` | |
| `sender` | FK → User, CASCADE | |
| `body` | TextField(4000) | |
| `created_at` | indexed | |
| `deleted_at` | DateTimeField, null | Soft delete (evidence for reports) |

- `Index(conversation, -created_at)` — the thread, paginated
- No per-message `is_read`; `ConversationParticipant.last_read_at` covers it in one row instead
  of N.

**Two rules for the Messaging seat, both non-negotiable:**

1. Every read goes through
   `Message.objects.filter(conversation__participants__user=request.user)`. Never trust a
   conversation id from the URL.
2. **Blocking never deletes a message.** Hiding is a filter (`visible_to()`), so unblocking
   restores the thread for free. There must be no code path anywhere that deletes a `Message`
   or `Conversation` on block — ADR-0002.

---

## 5. `notifications`

### 5.1 `Notification`

| Field | Type | Notes |
|---|---|---|
| `recipient` | FK → User, CASCADE, related_name=`notifications` | |
| `actor` | FK → User, CASCADE, null | Who did it |
| `kind` | CharField(20), choices | `new_message` / `new_follower` / `new_comment`. **No `new_spark`** |
| `post` | FK → Post, CASCADE, null | Nullable concrete FKs, one per target type |
| `comment` | FK → Comment, CASCADE, null | |
| `conversation` | FK → Conversation, CASCADE, null | |
| `is_read` | Boolean, default False | |
| `created_at` | indexed | |

- `Index(recipient, -created_at)` — the notifications screen
- **Partial** `Index(recipient) WHERE is_read = false` — the bell count, which runs on *every
  page load*. A partial index here is the difference between a scan and a lookup.
- `CheckConstraint`: `recipient != actor` (never notify yourself)

**Why concrete nullable FKs instead of a GenericForeignKey:** three target types, known and
closed. Concrete FKs give `select_related("actor", "post", "comment")` — one query for the whole
bell dropdown. A `GenericForeignKey` cannot be `select_related`ed and produces an N+1 by
construction.

### 5.2 Dedup rules — both of them (for the Social seat)

Notifications are the retention engine (spec §8), which means a noisy bell is a product failure,
not a cosmetic one. Two rules, not one:

1. **Comments:** don't create a second `new_comment` for the same post from the same actor
   within 60 seconds.
2. **Messages:** don't create a `new_message` for a conversation that **already has an unread
   `new_message` notification** for that recipient. Instead, bump the existing row's
   `created_at`.

Rule 2 was missing from the first draft and matters more than rule 1: without it, a ten-message
burst produces ten bell entries and buries every other notification the user has. Ten messages
in one conversation is one thing the user needs to know about, not ten.

**Blocking deletes notifications** where the other party is `actor` (ADR-0002), and the bell
query is `visible_to()`-filtered as a second line of defence.

---

## 6. `moderation`

### 6.1 `Report`

| Field | Type | Notes |
|---|---|---|
| `reporter` | FK → User, SET_NULL, null | Report survives the reporter deleting their account |
| `reported_user` | FK → User, CASCADE, null | Exactly one of these three is set |
| `post` | FK → Post, CASCADE, null | |
| `comment` | FK → Comment, CASCADE, null | |
| `reason` | CharField(20), choices | `spam` / `harassment` / `scam` / `inappropriate` / `impersonation` / `other` |
| `details` | TextField(1000), blank | |
| `status` | CharField(12), choices, default `open`, indexed | `open` / `reviewing` / `actioned` / `dismissed` |
| `resolution_note` | TextField(500), blank | |
| `reviewed_by` | FK → User, SET_NULL, null, related_name=`reports_reviewed` | |
| `reviewed_at` | DateTimeField, null | |
| `created_at` | indexed | |

- `CheckConstraint`: exactly one of `reported_user` / `post` / `comment` is non-null
- `Index(status, -created_at)` — the admin queue, oldest-open first
- **Conditional** `UniqueConstraint(reporter, post)` / `(reporter, comment)` /
  `(reporter, reported_user)` **with `condition=Q(status__in=["open", "reviewing"])`**

#### Why the unique constraints are conditional

The intent is "one **open** report per person per target" — enough to stop brigading. Written
without a condition it means "one report **ever**": someone reports a post, a moderator
dismisses it, the post gets worse, and that person can never report it again. The condition
makes the constraint match the intent, and it is a partial unique index in Postgres, so it
costs nothing.

No `ModerationAction` model in v1 — `status` + `resolution_note` + `reviewed_by` on the report is
enough for a Django-admin queue. Rate limiting is `django-ratelimit` against Redis; no table.

**Moderation queries deliberately bypass `visible_to()`.** A moderator must see blocked and
soft-deleted content or the queue is blind (ADR-0003).

---

## 7. Denormalized counters — the rules

`spark_count`, `comment_count`, `save_count`, `follower_count`, `following_count`, `post_count`,
`Tag.post_count`, `Role.usage_count`.

They exist because "sort the feed by most-sparked" with a live `COUNT(*)` join can't use an
index, and the feed is the most-hit query in the app.

**Rules for every seat:**

1. Never `obj.count += 1` in Python. Always
   `Post.objects.filter(pk=…).update(spark_count=F("spark_count") + 1)` — atomic, no lost
   updates under concurrency.
2. Do it in the same `transaction.atomic()` block as the row it counts.
3. `PositiveIntegerField` + guard the decrement so it can never go below zero.
4. A weekly reconciliation task recomputes all counters from the real rows. Drift happens; a
   cheap repair job is the honest answer. *(In production this runs via the GitHub Actions cron
   endpoint, not Celery Beat — `deployment.md` §4.)*

### 7.1 Soft deletes and counters — the rule that was missing

Soft-deleted rows are invisible to users, so **they do not count**:

| Action | Effect |
|---|---|
| Comment soft-deleted | `Post.comment_count` **−1** |
| Post soft-deleted | author's `Profile.post_count` **−1**; every `Tag.post_count` on it **−1** |
| Post soft-deleted | its sparks/saves/comments are **not** touched — the rows survive for moderation, but the post is gone from every list so its counters are moot |
| Message soft-deleted | no counter |
| Undelete | reverse each of the above |

Without this rule a post shows "12 comments" above 11 rendered ones the first time anyone
deletes a comment — a bug that looks like a caching problem and isn't. The reconciliation task
(rule 4) computes counts over `deleted_at__isnull=True` rows, so it agrees with this rule rather
than fighting it.

### 7.2 Counters are global, never viewer-relative

Blocking hides content but **does not change any counter** (ADR-0002). A viewer-relative count
would leak how many comments the blocked person wrote, and would mean an aggregate per card per
request. Post detail renders the length of the comment list it already fetched; feed cards
render the denormalized number. The two never appear on the same screen.

---

## 8. Deletion policy

| Object | Policy | Why |
|---|---|---|
| Post | **Soft** (`deleted_at`) | May be attached to an open report; hard delete destroys moderation evidence |
| Comment | **Soft** | Same. Comments are deletable but not editable |
| Message | **Soft** | Same |
| Spark / Save / Follow / Block | **Hard** | Pure edges, no evidential value, unbounded growth if kept |
| Notification | **Hard**, plus a job pruning read notifications older than 90 days | Otherwise this becomes the biggest table in the DB |
| **User account** | **Anonymise** — ADR-0001 | See below |

### 8.1 Account deletion = anonymise (ADR-0001) ✅

Deleting an account sets `deletion_requested_at` and starts a **30-day grace window**; logging
back in during the window cancels it. After 30 days a scheduled job:

- sets `is_active=False`, unusable password, placeholder email
- clears every identifying field on `Profile` (avatar, bio, headline, work_done, links,
  occupation, city, field_tag, interests, skills)
- **keeps** posts, comments and messages, attributed to a `[deleted]` placeholder
- **hard-deletes** follows, blocks, sparks, saves, and notifications where they are the actor

Their content survives because it is woven into other people's threads — a two-person
conversation must not become a monologue because one person left, and a moderation report must
not be neutralisable by deleting your account. Full reasoning and rejected alternatives in
ADR-0001.

**Every seat that renders a user must handle `[deleted]` safely** — cards, comments,
conversation headers, notifications.

### 8.2 Managers

All soft-deleted models get `objects = ActiveManager()` (filters `deleted_at__isnull=True`) plus
`all_objects = models.Manager()` for admin and moderation. Feature seats use `objects` and get
the right behaviour for free.

Combined with §1.6, an authenticated list view reads:

```python
Post.objects.visible_to(request.user)      # active + block-filtered
```

---

## 9. The eleven open questions — and Jeni's answers

All resolved 31 Jul 2026. Kept on the record so no seat re-litigates them.

| # | Question | Answer |
|---|---|---|
| **Q1** | What does "delete account" do? | ✅ **Anonymise**, 30-day grace window. ADR-0001 |
| **Q2** | Roles: fixed list or free text? | ✅ **Curated list + "Other" free text**, which feeds keyword search but not the filter. Topic tags: **user-created free text**, the opposite. ADR-0004 |
| **Q3** | Comment sparks in v1? | ✅ **In** — spec §4.4 already said "posts *and* comments" |
| **Q4** | Stale: separate flag or fourth status? | ✅ **Separate `is_stale` flag**, and stale posts are **ranked lower, never hidden**. Changed the feed indexes — §2.3.2 |
| **Q5** | What does Block do? | ✅ **Full mutual invisibility.** Chat history hidden, never deleted; restored on unblock. ADR-0002 |
| **Q6** | Location: free text or list? | ✅ **Free text + derived `city_slug`** for filtering |
| **Q7** | Profile links: fixed or a list? | ✅ **Three fixed URL fields** — matches spec §4.1 |
| **Q8** | How many images per post? | ✅ **5**, enforced in the form |
| **Q9** | Do sparks notify? | ✅ **No** — spec §4.6 lists three triggers, sparks isn't one |
| **Q10** | Can comments be edited? | ✅ **No.** Deletable, not editable. `is_edited` dropped |
| **Q11** | Is search over comments? | ✅ **No** — spec §4.3 says posts *and people* |

### 9.1 Problems found in the first draft and fixed

Recorded because the reasoning is worth keeping, and because two of these were invisible bugs:

1. **`Tag.kind` made Home tier 2 permanently empty.** The Home cascade would have silently
   fallen through to "newest posts" forever, with no error. Fixed by ADR-0004.
2. **The report unique constraint blocked re-reporting permanently** rather than only while a
   report was open. Fixed with a conditional constraint (§6.1).
3. **`is_demo` was doing two jobs** — seed lineage and write restriction — which collided with
   the read-mostly demo account decision in `testing.md` §7.5. Split (§1.1.1).
4. **`view_count`** was scope the spec never asked for, and the only counter needing a write on
   every anonymous page load. Cut.
5. **Avatar seeding was impossible** — `CloudinaryField` alone can't hold an external URL, so
   the seed couldn't produce 20 avatars idempotently. Added `avatar_url` (§1.2.1).
6. **Soft deletes had no counter rule** (§7.1), and **DM notifications had no dedup rule**
   (§5.2).
7. **`TextField(N)` was being read as a database limit.** It isn't (§0).
8. Doc accuracy: `dyad_key` nullability now stated in the field table; the `pg_trgm` index on
   `User.display_name` was listed under `Profile` and is now in the right section.

### 9.2 Still genuinely open — not blocking anyone

- **Fuzzy people search on `display_name`** needs a `GinIndex(gin_trgm_ops)` on `User`. Deferred
  to the `posts` 0003 extensions migration since `pg_trgm` must exist first. No seat is blocked.

---

## 10. Migration order

1. **`accounts` 0001** — `User` **only**. The custom user model must be first (roadmap ground
   rule 2), with `AUTH_USER_MODEL` set in `config/settings/base.py` before anything runs
2. `django.contrib.sites` + **allauth's own migrations** — allauth requires the sites framework
   and `SITE_ID`; this must precede any account flow
3. **`posts` 0001** — `Tag`, `Role`
4. **`posts` 0002 (data)** — seed ~15 curated field tags + ~40 curated roles. Must be a data
   migration, not ad hoc, or `Profile.field_tag` points at rows that differ per environment
5. **`accounts` 0002** — `Profile`, `ProfileSkill`, `ProfileInterest`, `Follow`, `Block`
6. **`posts` 0003** — `Post`, `PostTag`, `PostRole`, `PostImage`, `Comment`, `PostSpark`,
   `CommentSpark`, `SavedPost`
7. **`posts` 0004** — `pg_trgm` + `unaccent` extensions, `search_vector` columns, GIN indexes,
   trigram index on `User.display_name`
8. `messaging` 0001, `notifications` 0001, `moderation` 0001

Steps 1–5 must land before any feature seat starts. Steps 7–8 can follow their phases.

> **allauth's username generation** derives a username from the email address on Google sign-in,
> which can produce values that fail our `[a-z0-9_]{3,30}` validator (dots, plus signs,
> uppercase, length). The Accounts seat needs a custom adapter that normalises and
> de-duplicates. Flagged here because it is a schema-adjacent constraint, not a UI detail.

---

## 11. What each seat gets from this

| Seat | Owns behaviour over | Must not touch |
|---|---|---|
| Accounts & Profiles | `User`, `Profile`, `ProfileSkill`, `ProfileInterest`, `Follow`, `Block`, block-cache invalidation, `is_public_demo` enforcement | any `models.py` |
| Posts & Feed | `Post`, `PostTag`, `PostRole`, `PostImage`, `Tag`, `Role` | any `models.py` |
| Discovery | `search_vector`, `keywords`, `custom_roles` in search, all read queries, the Home cascade | any `models.py` |
| Social | `PostSpark`, `CommentSpark`, `Comment`, `SavedPost`, `Notification`, both dedup rules | any `models.py` |
| Messaging | `Conversation`, `ConversationParticipant`, `Message` | any `models.py` |
| Trust & Safety | `Report`, `Post.is_stale` / `nudged_at` / `last_activity_at`, the 30-day anonymise job | any `models.py` |
| QA | factories for all of the above; `is_demo=True` on seeded users | any `models.py` |

**Everyone:** authenticated list queries call `.visible_to(request.user)` (§1.6). Moderation
and admin deliberately do not.

Schema change requests go: seat → Jeni → Architect → this document → migration.
