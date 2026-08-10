# Data-model review — Discovery seat

**Reviewer:** Discovery · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock), ADR-0002/0003/0004,
`product-spec.md` §3.3 + §4.3, `tech-stack.md` §2
**Method:** walked every query I have to write — post search, people search, the four filters,
and all three Home tiers — against the declared columns and indexes, asking of each: which index
serves this, and what happens at 10k posts.

**Headline:** the model serves my area better than I expected, and the two hardest calls in it
(`is_stale` as a leading **sort column** rather than a partial-index condition, and blocking as a
cached id set rather than a per-query join) are both right. I found **14 things**. **Four are
schema changes that must land before lock** — three of them cheap, one of them the kind of silent
failure ADR-0004 exists to prevent. Five are product decisions only Jeni can make.

The must-land list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **D1** | `english_unaccent` text search configuration + a pinned `config=` everywhere | Retrofitting means rebuilding every `search_vector` in the database |
| **D3** | `is_stale` as 2nd column in the three filter indexes | Free now; an index rebuild on the hottest table later |
| **D4** | `User` trigram + `Profile` GIN indexes belong in an **`accounts`** migration, not `posts` 0004 | `makemigrations` will not produce what §10 describes |
| **D2** | Curated `Role` names + post `Tag` names into `Post.search_vector` | Doc-only, but it inverts who is findable — see below |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a column, index or migration-order change before lock |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but an interface other seats depend on and nobody has written down |
| ⚪ **Mine** | Discovery-side work. Listed so it's visible, not to create work for the Architect |

---

## 1 · Findings

### 🔴 D1 — the text search config is unpinned, and `unaccent` as specified does nothing

Neither `data-model.md` §3 nor `tech-stack.md` §2 names a text search configuration. Django's
`SearchVector` falls back to the database's `default_text_search_config`, which varies with the
Postgres image's initdb locale — so the same code produces `english` stemming in Docker and
possibly `simple` (no stemming at all) on Neon. **A stored vector built under one config and
queried under another silently drops matches and returns meaningless ranks.** Same failure shape
as `Tag.kind`: well-formed, indexed, quietly wrong.

Worse, §3 promises the `unaccent` extension, but `unaccent(text)` is `STABLE`, not `IMMUTABLE`,
so it cannot appear in an indexed expression, and `SearchQuery` never applies it. Enabling the
extension alone buys nothing — "sao paulo" still will not match "São Paulo".

**Ask —** the extensions migration (§10 step 7) also creates:

```sql
CREATE TEXT SEARCH CONFIGURATION english_unaccent ( COPY = english );
ALTER TEXT SEARCH CONFIGURATION english_unaccent
  ALTER MAPPING FOR hword, hword_part, word WITH unaccent, english_stem;
```

and `data-model.md` records that **every** `SearchVector` and `SearchQuery` in the codebase pins
`config="english_unaccent"`. This must land before any vector is written; changing it afterwards
invalidates every stored vector in the database.

---

### 🔴 D2 — the post vector indexes the free-text role and omits the curated one

§2.3 defines `Post.search_vector` as `title` A · `keywords` + `custom_roles` B · `body` C.

Three things are missing, and the first is an inversion:

1. **Curated `Role` names are absent.** `custom_roles` — the "Other" free-text box — is in at
   weight B. The curated `Role` rows are in at nothing. So searching *"illustrator"* finds the
   post where somebody typed it into the Other box and **misses every post that correctly
   selected the curated Illustrator role.** The user who filled the form properly is the one who
   becomes unfindable. ADR-0004 action item 4 made the free-text value searchable and left the
   primary value out.
2. **Post tags are absent.** A post tagged `fintech` where the word appears in neither title nor
   body is not findable by searching "fintech" — despite tags being the strongest topical signal
   in the schema.
3. **`city` is absent.** "Nairobi" should find posts in Nairobi. Weight C or D.

**No new columns.** This is a §2.3 correction plus my implementation — but it carries a rule the
doc does not state and that I cannot enforce alone:

> The vector must rebuild on **`m2m_changed` for `PostTag` and `PostRole`**, not only on
> `Post.save()`. Editing a post's tags or roles currently leaves the vector stale with no error.

Proposed §2.3 replacement: `title` **A** · `tags.name` + `roles_needed.name` + `custom_roles` +
`keywords` **B** · `body` **C** · `city` **D**. Built in Python inside the refresh task, per §3.

---

### 🔴 D3 — the filter indexes drop stale demotion

Q4 makes `is_stale` the **leading sort column** (`ORDER BY is_stale ASC, published_at DESC`), and
§2.3.2's two feed indexes match it column for column. That is correct and I am not touching it.

But the three Discovery filter indexes — `(city_slug, -published_at)`, `(commitment,
-published_at)`, `(stage, -published_at)` — do **not** lead with `is_stale`. So a filtered view
either sorts unindexed or silently drops the demotion, in the one place a result set is small
enough for a stale post at the top to be the whole screen.

**Ask —** `(city_slug, is_stale, -published_at)`, `(commitment, is_stale, -published_at)`,
`(stage, is_stale, -published_at)`, same partial condition as the feed indexes. Costs nothing to
write now; costs an index rebuild on the hottest table in the app later.

**Minor, same area:** the standalone `db_index=True` on `is_stale` earns nothing. A boolean where
~90% of rows are `false` will not be chosen by the planner, and it costs write throughput on
every post edit. The two composites cover every read. Recommend dropping it.

---

### 🔴 D4 — two indexes are declared in the wrong app, and §1.2 contradicts §10

§9.2 defers the trigram index on `User.display_name` to **`posts` 0004**. An `AddIndex` against
`accounts.User` cannot live in a `posts` migration — `makemigrations` will generate it into
`accounts` and the two will disagree. It needs an **`accounts` 0003** with `dependencies` on the
posts extensions migration (the extension itself is schema-level and can stay in `posts` 0004).

The same problem, plus a contradiction, for `Profile.search_vector`'s GIN index: §1.2 lists it
under Profile (which lands in `accounts` 0002), §10 step 7 puts *all* GIN indexes in `posts`
0004. **Those two sections disagree and both cannot be built.** Same fix: `accounts` 0003.

**Also missing —** the trigram index is specified on `display_name` only. People search by handle
(`@jen`), and `username`'s unique btree cannot serve `ILIKE '%jen%'`. Add
`GinIndex(username, gin_trgm_ops)` in the same migration.

---

### 🟠 D5 — tier 2's window is undefined, and its likely answer is "empty"

§3 says "most-sparked posts carrying your `field_tag`, last 7 days." Two undefined things, and
they interact:

- **Last 7 days of what?** `published_at` gives genuinely new posts. `last_activity_at` resurfaces
  older posts with recent buzz. These are different products.
- **`spark_count` is lifetime, not windowed.** Under a `published_at` window that is near enough.
  Under a `last_activity_at` window, a post with 200 lifetime sparks dominates its field forever.

And the case that puts us back in ADR-0004's hole by a different door: on a young site, *posts
carrying your exact field tag, published in the last 7 days* will frequently be **zero rows**.
The cascade then falls to tier 3 and the personalisation never happens — which is precisely the
symptom ADR-0004 was written to eliminate, arriving as a data-volume problem instead of a schema
one.

**Recommendation:** window on `published_at`, and when 7 days is empty, **widen to 30 days before
falling through to tier 3**. Widening keeps Home personal; falling through does not.

**Schema consequence:** none, if we window on `published_at`. If Jeni wants true
sparks-in-the-window instead, I need `PostSpark Index(post, created_at)` — the declared
`Index(target)` and `Index(user, -created_at)` do not serve "sparks on this post since date".
Conditional on the answer.

---

### 🟠 D6 — a user who skips onboarding has no tier 1 *and* no tier 2

All onboarding is optional (spec §3.1) and `Profile.field_tag` is nullable. A user who skips step
2 has no field tag and no interest tags, so tiers 1 and 2 are both structurally impossible and
their Home is "newest posts overall" permanently — the exact cold-start failure §4.3 exists to
prevent, for the users most likely to bounce.

**Recommendation:** insert a tier 2.5 before raw newest — *most-sparked posts this week across the
highest-`post_count` curated tags*. A real popularity feed rather than a chronological one, and
because it is identical for every such user it is one cached query shared by all of them. No
schema change; needs a ruling because it adds a band to a cascade the spec defines as three.

---

### 🟠 D7 — does search return `team_formed` and `closed` posts?

§4.8 gets those statuses out of the active **feed**, and §2.3.2's partial indexes encode that.
Search is a different intent: someone looking for a specific project by name should find it, and
"this team already formed" is useful information, not noise.

**Recommendation:** searchable, ranked below `looking`. Feed and filters keep excluding them.
No schema change either way — the GIN index does not carry the partial condition — but it changes
what QA asserts, so it should be on the record.

---

### 🟠 D8 — stale demotion is a hard split, not a demotion

`ORDER BY is_stale ASC` sorts **every** stale post below **every** fresh post. On the "most
sparked" sort that means a stale post with 300 sparks lands beneath a fresh post with zero. Q4
says "ranked lower, never hidden", and a hard split satisfies the letter of that — but it buries
the best content in the app rather than demoting it.

**Recommendation:** keep the hard split on the Feed, where it is served by an index and therefore
free, and apply a graded penalty inside Home and search, where a sort is unavoidable anyway.
Costs nothing either way; I want it decided rather than discovered.

---

### 🟠 D9 — tag fragmentation is the unfixed half of ADR-0004

**Asked to verify the tier-2 fix holds for my query: the schema half holds.** `field_tag` points
at an ordinary `Tag`, there is no `kind` column, and tier 2 is structurally capable of returning
rows. Confirmed.

**The data half does not, and nothing records it.** Tier 2 returns rows only if posts actually
carry the ~15 curated tags — and topic tags are user-created free text (Q2). A user who types
`ml` rather than `machine-learning`, or `AI stuff`, creates a tag no `field_tag` points at.
`Tag.slug`'s uniqueness collapses `"Machine Learning"` and `"machine learning"`; it does nothing
for `ml`.

ADR-0004's Consequences section catches this for the **seed corpus** but not for production. In
production, tier 2's hit rate decays as the vocabulary fragments, and it decays silently.

**Recommendation:** tag type-ahead in the composer, querying existing tags with curated ones
ranked first, so `ml` offers `machine-learning` before creating a new row. Needs a ruling because
it is the Posts seat's composer plus a suggestion endpoint from me. No schema change —
`Tag.slug` (unique, indexed) and `Tag.post_count` are already everything the endpoint needs.

---

### 🟡 D10 — `Profile.search_vector` has no defined contents, and depends on a table I don't own

§2.3 specifies `Post`'s vector to the weight. §1.2 gives `Profile.search_vector` a column and a
GIN index and **never says what goes in it.**

The complication: the two highest-signal fields for finding a person — `username` and
`display_name` — live on **`User`**, not `Profile`. Reaching across the 1:1 is fine when the
vector is built in Python, but it creates a cross-seat contract that must be written down:

> **Accounts must trigger a `Profile.search_vector` rebuild when `User.display_name` or
> `User.username` changes.** Otherwise renaming yourself makes you unfindable under your new name,
> with no error anywhere.

Proposed §1.2 text: `user.display_name` + `user.username` **A** · `headline` + `occupation` +
`custom_skills` + `skills.name` **B** · `bio` + `work_done` **C** · `city` **D**.

(ADR-0004 says `custom_skills` is the symmetric case to `custom_roles` but never actually puts it
in a vector. This is where it goes.)

---

### 🟡 D11 — `visible_to()` should short-circuit on an empty block set

ADR-0003 makes `visible_to()` a no-op for **anonymous** users. Make it a no-op for an
**authenticated user whose block set is empty** as well — which is the overwhelming majority of
logged-in users.

As written, every authenticated feed, Home and search query carries an `.exclude(author_id__in=
[])` forever, on the hottest queries in the app, to filter nothing. One line in `visible_to()`,
and it should land before six seats copy the pattern.

**Recording one thing as mine:** my per-field-tag tier-2 cache (D14) is shared across viewers, so
it caches post **ids** and applies the block filter per-request after the cache read, never
before it. Written down here so QA's `tests/cross/test_block_visibility.py` and I agree in
advance.

---

### 🟡 D12 — the cascade cannot be paginated with OFFSET (answers Designer GAP 4)

A three-tier top-up cannot be paginated by offset: if tier 1 yields 12 rows and tiers 2–3 fill
the rest, the tier boundaries shift as posts arrive, and rows duplicate and vanish between pages.
Django's `Paginator` over a dynamically-composed union is wrong here.

**Approach, needing no schema change:** resolve the whole cascade once per request into a single
ordered list of post ids, cache it in Redis per user for 60–120s, and paginate over the cached
list. Stable pagination, one query per page, and "load more" behaves.

**This also answers the Designer's GAP 4** — that cached list stores `(post_id, tier)` pairs, so
tier provenance comes free and the Home bands can be labelled *from people you follow* /
*because you picked android* / *newest overall*. Confirmed: Discovery will expose the tier marker,
and it is cheap precisely because it is decided now rather than after the view is written.

**Designer GAP 10 (search highlighting):** in scope, no schema change. Postgres `ts_headline()`
over the stored vector's source columns. I'll build it.

---

### ⚪ D13 — what I verified rather than asked for

Recording these so nobody re-reviews them, and so the Architect can see which asks I dropped:

- **Tier-1 index paths are all covered.** `Post Index(author, -published_at)` for the follow leg.
  The followed-id lookup is **index-only** off `Follow`'s `UniqueConstraint(follower, following)`
  — so the covering column I was going to request is unnecessary. Same for
  `ProfileInterest`'s `UniqueConstraint(profile, tag)` (profile → tag ids) and
  `PostTag Index(tag, post)` (tag → post ids).
- **Tier 3** is served exactly by `Index(is_stale, -published_at)` partial. Nothing needed.
- **I do not need a `search_vector_updated_at` column.** A full nightly rebuild is cheaper than a
  column at this scale, and it repairs vectors that are stale-but-non-null, which a NULL check
  cannot find. Dropping the ask.
- **`GinIndex(keywords)`** is currently declared for a query the cascade does not make. I will use
  it for `keywords__overlap` on "related posts" — so keep it, but it is earning its place on my
  say-so, not the doc's.
- **Combined filters** (tag + commitment + location) bitmap-AND across the single-column
  composites. Fine at v1 scale. No composite-of-composites needed.
- **Blocking needs no join and no new index.** ADR-0003's cached frozenset is the right call and I
  am not relitigating it. `visible_to()` on `Profile` is already in ADR-0003's action items, which
  is what people search needs.
- **Discovery still needs no models of its own.** §3 is correct.

---

### ⚪ D14 — performance position, on the record

Search and Home stay comfortable to roughly 10k posts. Two things break first:

1. **Tag-filtered ordering.** No index gives tag → posts *in `published_at` order*, so a popular
   tag sorts its whole post set to return 20. §2.3.2 tells me not to denormalise `published_at`
   onto `PostTag` until `EXPLAIN` says so — **agreed, and I am accepting that.** Recording it as
   the first thing to break, with a known fix.
2. **`SearchRank` sorting a large match set.** Ranking is a computed value, so no index can serve
   the ordering. Fix is capping the candidate set with a trigram/GIN prefilter before ranking.

Neither needs a schema change now. Two mitigations I am building that do not either:

- **Tier 2 cached per field tag, not per user.** The query is identical for every user sharing a
  field tag and there are only ~15 of them — that collapses N per-user queries into 15.
- **Followed-id and interest-tag-id sets cached per user**, same shape as ADR-0003's block set:
  small, per-user, changes rarely. Removes two subqueries from the most personal query in the app.

I will bring `EXPLAIN ANALYZE` against QA's seed corpus rather than a hunch.

---

## 2 · What I need back

1. **Four schema changes — D1, D3, D4, D2.** D1 and D4 are correctness (D4 will not build as
   written); D3 is free now and expensive later; D2 is doc-only but inverts who is findable.
2. **Five decisions from Jeni** — D5 (tier-2 window), D6 (skipped-onboarding tier), D7 (search vs
   `team_formed`), D8 (hard split vs graded demotion), D9 (tag type-ahead). D5 is the only one
   that may add an index.
3. **Two contracts written into the doc** — D10 (`Profile.search_vector` contents + the Accounts
   rebuild trigger) and D2's `m2m_changed` rule. Both are cross-seat and neither is enforceable
   from my side alone.
4. **One line from the Architect** — D11, the empty-block-set short-circuit, before other seats
   copy the pattern.

Everything else in the model I'd build against as-is. I have not touched `models.py` or any
migration.
