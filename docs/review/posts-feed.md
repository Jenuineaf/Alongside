# Data-model review — Posts & Feed seat

**Reviewer:** Posts & Feed · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock) — §2.1–2.5, §2.3.2, §7, §7.1,
§7.2, §8, §10, and ADR-0004
**Scope:** `Post`, `Tag`, `Role`, `PostTag`, `PostRole`, `PostImage`, feed ordering, pagination,
soft delete, staleness. Sparks/comments (Social), search/filters (Discovery) and the nudge job
(Trust & Safety) only where they touch my columns.

**Headline:** the shape is right and I can build on it. The `is_stale` / `status` split is
modelled correctly and `published_at` being writable is the right call for two separate reasons.
I found **14 things**. Three are schema changes I'd argue must land before lock; five are
product decisions only Jeni can make; the rest are contracts or my own implementation notes.

**Four of these fail silently** — no error, no bug report, just a feature that ships looking fine
and does nothing. Same class as the `Tag.kind` bug ADR-0004 caught. Those are PF-1, PF-2, PF-3
and PF-5.

The must-land-before-lock list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **PF-1** | `-id` appended to both feed indexes | Once cursors are in URLs, changing the sort tuple breaks every open tab. Index-only change today |
| **PF-2** | `Post.touch_activity()` — one place that clears `is_stale` | Three seats write `last_activity_at`. Without one method they each implement half of it |
| **PF-3** | `last_activity_at` writable, `default=timezone.now` | Otherwise no seeded post is ever stale and the anti-ghosting feature is undemoable and untestable |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a field, index or model method before lock |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but an interface other seats depend on and nobody has written down |
| ⚪ **Mine** | My implementation debt. Listed so it's visible, not to create work for the Architect |

---

## 1 · Findings

### 🔴 PF-1 — The feed indexes have no unique tiebreaker, so infinite scroll will duplicate and skip cards

First, the part that is **correct**: `Index(is_stale, -spark_count, -published_at)` emits
`(is_stale, spark_count DESC, published_at DESC)`, which matches
`ORDER BY is_stale ASC, spark_count DESC, published_at DESC` exactly — forward index scan, no
sort node. The "most-sparked" index works. The problem is the tuple is incomplete.

`(is_stale, spark_count, published_at)` is **not unique**. The seed writes arbitrary
`published_at` values across 90 days (`testing.md` §7.2), so collisions are near-certain in the
demo corpus, and real posting bursts collide too. Any pagination that cannot fully order rows
will repeat some cards and silently drop others as the user scrolls.

Worse on the "most sparked" tab: **`spark_count` mutates while the user is paginating.** Someone
scrolls for thirty seconds, three sparks land, and page 3 re-shows a card from page 2.
`LIMIT/OFFSET` makes this certain; keyset makes it rare but not impossible.

**Change:**

```python
Index(fields=["is_stale", "-published_at", "-id"], condition=…)          # newest
Index(fields=["is_stale", "-spark_count", "-published_at", "-id"], …)    # most sparked
```

Partial conditions unchanged (`deleted_at IS NULL AND status='looking'`).

**Mine to build on top:** keyset (cursor) pagination rather than offset, plus a client-side
de-dupe by post id in the HTMX partial to absorb the residual mutation case. I'll document the
cursor format in `docs/` when the feed lands.

**Why now:** index-only, costs nothing today. After the feed ships, cursor tuples are in live
URLs and HTMX request params, and changing the sort key breaks every open tab.

---

### 🔴 PF-2 — Nothing ever clears `is_stale`. A revived post stays sunk forever.

§2.3 says `last_activity_at` is "bumped by spark/comment/edit" and that `is_stale` is set by the
nudge job. **Nothing in the document sets `is_stale` back to `False`.**

An author answers the nudge, edits the post, gets five sparks and two comments — the post is
demonstrably alive and it sits at the bottom of every feed permanently. It never errors and the
post is still visible, so it reads as "the feed is a bit weird" and nobody ever finds it.

It is also cross-seat, which is what makes it certain rather than likely: **Social** bumps
`last_activity_at` on spark and comment, **I** bump it on edit and on status change,
**Trust & Safety** touches it on nudge response. Three seats who cannot see each other's chats
will each implement part of this, and the part everyone forgets is the flag.

**Change — one method on the model, owned by the Architect, called by everyone:**

```python
# Post
def touch_activity(self):
    Post.all_objects.filter(pk=self.pk).update(
        last_activity_at=Now(), is_stale=False
    )
```

Plus a documented rule in §2.3: **no seat writes `last_activity_at` or `is_stale` directly.**
Must be `.update()`, not `.save()` — see PF-9.

---

### 🔴 PF-3 — `last_activity_at` has no writable default, which makes staleness undemoable

§2.3.1 solves exactly this problem for `published_at`: `created_at` is `auto_now_add` and
therefore immutable, so the seed needs a writable ordering key. The same trap is one row down
and unaddressed.

If `last_activity_at` is populated at insert time, all 45 seeded posts have
`last_activity_at = today`. Consequences:

- No seeded post is ever stale. The nudge job has nothing to act on.
- My stale-ranking has nothing to demonstrate — the single most interesting piece of the
  anti-ghosting design (spec §4.8) is invisible in the demo.
- QA cannot write a meaningful `test_stale_ranks_lower` against seed data.

**Change:** `last_activity_at = DateTimeField(default=timezone.now, db_index=True)` — plainly
writable, no `auto_now`. Plus a line in §2.3 and a note to QA: the seed sets it alongside
`published_at`, with a handful of posts deliberately 45+ days cold and pre-flagged
`is_stale=True` so the ranking is visible on the deployed demo.

---

### 🟡 PF-4 — Curated `Role.name` and `Tag.name` are not in the search vector

§2.3 defines `search_vector` as `title A · keywords + custom_roles B · body C`.

`custom_roles` is in it — correct, and it honours the CEO requirement in ADR-0004. But the
curated `Role.name` and `Tag.name` values reached through `PostRole` / `PostTag` are **not**. So:

| Post | Searching `illustrator` finds it? |
|---|---|
| Picked the curated role **"Illustrator"** | ❌ (unless the word happens to be in the body) |
| Typed `illustrator` into the **Other** box | ✅ |

The user who filled the form in correctly is punished, and the curated vocabulary — the thing
ADR-0004 argues for — is the less discoverable option. Same for tags: a post tagged `crochet`
is not findable by searching "crochet" unless Discovery's keyword extraction happened to pull
that word from the prose.

**No new column.** The vector definition in §2.3 should read
`title A · keywords + custom_roles + tag names + role names B · body C`.

**Timing consequence that must be written down (this is the invisible half):** M2M rows are
written *after* the post row is saved. A vector computed in `post_save` will permanently contain
no tags and no roles for every post ever created. It must be refreshed after the M2M write.

**Contract I'm proposing:** Discovery exposes `refresh_search_vector(post)`; I call it once at
the end of my create/edit transaction after tags, roles and images are attached. Not a
`m2m_changed` signal — that fires four times per save and recomputes the vector each time.

**One note for Discovery via Jeni:** `custom_roles` is a `text[]` and cannot be passed to
`SearchVector` directly; it needs `array_to_string(custom_roles, ' ')`. And per
`deployment.md` §4, `CELERY_TASK_ALWAYS_EAGER=True` in prod, so this runs inline inside my
create-post request.

---

### 🔴 PF-5 — `Post.body` is the only `TextField` in the document with no length, and >1MB crashes post creation

Every other freeform field carries a form-level cap: `bio` 500, `work_done` 1000,
`Comment.body` 2000, `Message.body` 4000. `body` has none.

Postgres `to_tsvector()` hard-errors above 1MB of input (`string is too long for tsvector`).
With `CELERY_TASK_ALWAYS_EAGER` in prod that is a **500 on the create-post request**, raised
inside my transaction, on a path any user can trigger by pasting a large document. Unbounded
body also renders unbounded on a 375px post detail page.

**Change:** a documented cap in §2.3. I propose **20,000 characters** — far longer than any real
idea write-up, far under the tsvector ceiling.

Enforced in my form **and** the DRF serializer. §0 is right that `TextField(N)` is form-only;
since DRF is in the stack, "enforced in the form" is not sufficient on its own. Same reasoning
applies to the image cap (§2.5) and the `custom_roles` cap.

---

### 🟡 PF-6 — Counter rules: one column undefined, one operation uncovered, one contradiction

§7.1 was a good catch and is nearly complete. Three gaps. All of them corrupt `spark_count`,
which is a **sort key for my feed** — so a bad counter does not just show a wrong number, it
orders the feed wrongly.

**(a) `Role.usage_count` is undefined and unmaintained.** §7.1 decrements `Tag.post_count` on
post soft-delete but never mentions `Role.usage_count`. It is also ambiguous whether it counts
posts (`PostRole`) or profiles (`ProfileSkill`) or both — two seats will increment the same
column with different meanings and the weekly reconciliation task (§7 rule 4) cannot be written
against it.
**Proposal:** `usage_count` = **live posts requesting the role**. Posts only. Accounts does not
touch it. If profile-side popularity is wanted later it gets its own column.

**(b) Post *edit* has no counter rule.** Changing a post's tags from A to B must decrement
`Tag.post_count` on A and increment on B; same for `Role.usage_count`. §7.1 covers
delete/undelete only. This is mine to implement, but the rule belongs in §7.1 so QA's
reconciliation test agrees with me instead of fighting me.

**(c) §7.2 contradicts §1.4 and §8.1.** §7.2 says "blocking hides content but does not change
any counter." But §1.4 and ADR-0002 say follow rows in **both** directions are hard-deleted at
block time — so `follower_count` / `following_count` genuinely must decrease or they permanently
over-count. Likewise §8.1 hard-deletes an anonymised user's sparks and saves without saying to
decrement `spark_count` / `save_count` on **other people's posts**, which silently inflates my
"most sparked" ranking every time anyone leaves.

Not my counters, but they are my sort key. Suggested wording for §7.2:

> Blocking changes no counter **except** the follow counters, whose rows are actually deleted.
> Any hard-delete of an edge row decrements its target's counter.

---

### 🟠 PF-7 — Can a post have zero roles-needed?

The schema allows it and nothing in the spec answers it.

**Recommendation: require at least one** (curated or Other). A post with no roles can never
appear in a role-filtered result, which is the joiner's primary path — roadmap §1.3, *"filter by
the role you can fill."* It is also an idea posted with no signal about what is wanted, which is
the expectation-mismatch pattern spec §4.8 exists to prevent.

To keep the escape hatch honest, add **one more curated role: "Open to anyone / not sure yet."**
Then "I'm open to anything" is a filterable value rather than a null hole.

**Why this is in the schema list:** that role is one extra row in the **posts 0002 data
migration** (§10 step 4), which runs before my models exist. Decide before step 4, not after.

---

### 🟠 PF-8 — No cap on tags-per-post or curated-roles-per-post

`custom_roles` is capped at 3 and images at 5, but the M2M sides are uncapped. Forty tags on one
post puts it on every tag page and inflates `Tag.post_count` sitewide — a real spam vector, and
`Tag.post_count` is what drives tag suggestions (§2.1).

**Recommendation: 5 tags, 5 curated roles**, enforced in form and serializer. Form-level only,
no DB constraint — consistent with how the image cap was decided (§9 Q8).

**Related, same decision:** should a post be allowed with **zero tags**? Recommend requiring one.
A post with no tags can only ever surface in Home tier 3 — it is invisible to exactly the
personalisation ADR-0004 was written to make work.

---

### 🟠 PF-9 — The stale partition is a hard block; the consequence should be an explicit choice

`ORDER BY is_stale ASC, spark_count DESC` means **every** non-stale post outranks **every** stale
one. On the "Most sparked" tab, the single most-sparked idea on the site can be absent from page
1 if it has gone quiet.

That is a faithful reading of "ranked lower, never hidden," it is index-friendly, and **I
recommend keeping it for v1.** Flagging it because it is a visible consequence Jeni should agree
to rather than discover. If the preference is that stale posts are *penalised* rather than
*partitioned*, that is a stored `rank_score` column and I want it requested now, not retrofitted
onto a shipped feed.

Related and cheap to note: "most sparked" over all time means page 1 ossifies once the site has
history — new posts can never reach the top. Not a v1 problem at demo scale, and the fix is the
same `rank_score` column.

---

### 🟠 PF-10 — Two-phase staleness has no numbers

Spec §4.8: nudge at ~30 days, "no response → auto-marked inactive and demoted." The schema
carries both `nudged_at` and `is_stale`, but the document never states the second interval.

**Recommendation:** nudge at **30 days** of no activity; set `is_stale` at **37** if still
nothing.

Trust & Safety owns the job; I own what the ranking does with the flag, so I need the number to
write tests against. Related: the job's queryset should be explicitly
`status='looking' AND deleted_at IS NULL` — nudging someone who already marked "team formed" is
a bad experience, and their post is out of the feed anyway.

---

### 🟡 PF-11 — System writes to `Post` must use `.update()`, never `.save()`

`updated_at` is `auto_now`. `QuerySet.update()` does not fire it; `Model.save()` does. So a
stale-flag write or a search-vector refresh done via `.save()` puts "edited just now" on posts
nobody touched.

The rule is free — it just has to be **known** by the two other seats that write to `Post`
(Trust & Safety: `is_stale` / `nudged_at`; Discovery: `search_vector` / `keywords`). One line in
§2.3 next to the counter rules in §7.

---

### 🟡 PF-12 — Cloudinary assets on soft-deleted posts have no cleanup story

Soft delete means we cannot purge a post's Cloudinary assets, because undelete must restore
them (§7.1). So every deleted post's images stay in the account permanently, on a free tier with
a storage cap.

No schema change requested — there is no clean fix that preserves undelete. Recording it so it
lands on DevOps' radar as a future retention job rather than being discovered as a quota error.
Distinct from the case I *do* handle: an image removed during an edit is a hard `PostImage`
delete and destroys its Cloudinary asset via `post_delete` (PF-14).

---

### ⚪ PF-13 — `slugify(title)` returns empty for a non-Latin title

`slugify("नमस्ते")` with `allow_unicode=False` is `""`. Plausible for our audience — Devanagari
or CJK titles are not an edge case in an India-first product. The post still gets a unique slug
from the random suffix, so nothing breaks, but the URL is a bare hash.

Mine to handle: fall back to a stable prefix when the slugified title is empty, and truncate the
title portion so `slugify(title) + suffix` always fits `SlugField(160)`. Noting it so the
Architect does not also solve it.

---

### ⚪ PF-14 — My implementation notes, for visibility only

- `PostImage` hard-deleted during an edit destroys its Cloudinary asset via `post_delete`.
- Feed cards render the denormalized counters; post detail renders `len()` of the comment list
  it already fetched. Consistent with §7.2 — the two never appear on the same screen.
- I build the feed as `Post.objects.visible_to(user)` with ordering applied last, so Discovery's
  filters attach as `.filter()` layers and Social's spark/save state as annotations. Nobody has
  to rewrite my ordering to add a filter.
- Non-partial indexes on `(author, -published_at)`, `(status, -published_at)` and the Discovery
  filter indexes scan soft-deleted rows before filtering them. Correct at v1 scale — **not**
  requesting a change. `Index(-last_activity_at)` would ideally be partial on the nudge job's
  actual queryset, but same conclusion: not worth a migration line today.

---

## 2 · Schema change requests — the list for the Architect

| # | Request | Cost | Blocking? |
|---|---|---|---|
| PF-1 | Append `-id` to both feed indexes | Index-only | **Yes** — expensive after the feed ships |
| PF-2 | `Post.touch_activity()` sets `last_activity_at=Now(), is_stale=False` in one `.update()` | One method | **Yes** — three seats depend on it |
| PF-3 | `last_activity_at`: `default=timezone.now`, writable, seed-settable | Field default | **Yes** — feature is undemoable without it |
| PF-7 | One extra curated role: "Open to anyone / not sure yet" | One data-migration row | **Yes if PF-7 is approved** — §10 step 4 runs first |
| PF-4 | Doc: vector includes tag + role names; refreshed after M2M write, not `post_save` | Doc | No, but decide before Discovery starts |
| PF-5 | Doc: `Post.body` cap, proposed 20,000 | Doc | No |
| PF-6 | Doc: `Role.usage_count` semantics; counter rules on post edit; fix the §7.2 / §1.4 contradiction | Doc | No |
| PF-11 | Doc: system writes to `Post` use `.update()`, never `.save()` | Doc | No |

Three index/field/method changes and five paragraphs of documentation. Nothing here is a
rewrite.

## 3 · Decisions needed from Jeni

| # | Question | My recommendation |
|---|---|---|
| PF-7 | Can a post have zero roles-needed? | **No** — require ≥1, plus an "Open to anyone" curated role so the escape hatch stays filterable |
| PF-8 | Cap on tags and roles per post? Zero tags allowed? | **5 and 5.** Require ≥1 tag |
| PF-9 | Accept that a stale post never outranks a fresh one, even on "Most sparked"? | **Accept for v1.** Alternative is a `rank_score` column, and it must be requested now |
| PF-10 | Second staleness interval | Nudge at **30** days, flag stale at **37** |
| PF-5 | Body length cap | **20,000 characters** |

---

**Status:** waiting on Jeni for §3, and on the Architect for §2. Not writing code until the
migration is locked (`CONTRIBUTING.md` rule 5).
