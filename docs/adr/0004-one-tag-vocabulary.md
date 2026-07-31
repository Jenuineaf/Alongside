# ADR-0004: One tag vocabulary — drop `Tag.kind`, and how roles differ

**Status:** Accepted
**Date:** 31 Jul 2026
**Deciders:** Jeni (CEO) · Architect
**Affects:** Discovery (Home cascade, filters) · Posts & Feed · Accounts (onboarding) · QA (seed corpus)

## Context

`product-spec.md` §4.3 specifies a three-tier cascading fallback so a new user's Home feed is
never empty:

1. people you follow + your interest tags
2. → not enough? **top posts in your field this week**
3. → still not enough? newest posts overall

The tier-2 clause is the reason `Profile` carries a normalised `field_tag` at all: free-text
`occupation` cannot drive a query.

The first draft of `data-model.md` modelled this with a `Tag.kind` column taking values
`topic` / `field`, so that `Profile.field_tag` could reuse the `Tag` table — and, in the
draft's own words, *"without polluting tag suggestions."*

**That construction makes tier 2 permanently return zero rows.** Posts are tagged with *topic*
tags. A profile's field is a *field* tag. The `kind` column exists precisely to keep those two
sets apart and keep field tags out of the suggestion list — so no post will ever carry the tag
that tier 2 has to match on. The query is well-formed, indexed, and empty for every user
forever.

It would not have surfaced as a bug report either. Tier 2 failing is invisible: the cascade
falls through to tier 3, Home fills with newest posts, and everything looks like it works. The
personalisation would simply never have happened.

## Decision

**Delete `Tag.kind`. There is one tag vocabulary.**

`Profile.field_tag` becomes a foreign key to an ordinary `Tag` — the same rows posts are tagged
with. "Top posts in your field this week" is then a real query over real rows: *the most-sparked
posts carrying that tag in the last 7 days.*

Supporting decisions:

- **`Tag.is_curated`** (already in the draft) does the job `kind` was reaching for. A seeded set
  of ~15 broad, curated tags — `software`, `crochet-and-craft`, `fintech`, `climate`,
  `edtech`, … — populates the onboarding "what's your field?" picker. They are ordinary tags;
  posts can and should carry them.
- **Topic tags are user-created free text.** ✅ *Confirmed by Jeni, 31 Jul.* Tags are matched by
  search and keyword, not by exact-match filtering, so vocabulary drift costs little and
  expressiveness is worth more.
- **Roles are the opposite, and stay a separate model.** ✅ *Confirmed by Jeni, 31 Jul —
  curated list plus an "Other" free-text box.* See below.

### Why roles are still a separate table

Tags and roles are now the only two vocabularies, and it is worth stating plainly why they get
opposite treatment rather than being merged:

|  | Topic tags | Roles |
|---|---|---|
| Describes | what an idea is *about* | what a *person* does |
| Created by | anyone, freely | curated list + "Other" |
| Used for | search, keyword matching, Home tier 1 | **exact-match filtering** |
| Drift cost | low — search tolerates it | **high — breaks the filter** |

Filtering by "role needed" only works if everyone picks from one vocabulary. If one person
writes "Backend Dev" and another "backend engineer", the filter silently returns half the
results — the same class of invisible failure as the `kind` bug above. Tags never carry that
risk because nothing does an exact match on them.

### The "Other" free-text role, and the search requirement

**CEO requirement, 31 Jul:** *"the free-text value should still feed keyword search, so an
unusual role is findable by search even though it doesn't appear in the role filter."*

Implemented as `Post.custom_roles` — `ArrayField(CharField(50))`, capped at 3, default empty:

- rendered on the post alongside the curated roles, visually identical to the user
- **included in `Post.search_vector` at weight B**, so "puppeteer" finds the post
- **excluded from the role filter**, which only ever offers curated `Role` rows

So an unusual role is discoverable by search and never fragments the filter. The same field
exists on `Profile` as `custom_skills` for the symmetric case — someone whose skill is not on
the list.

This is exactly what option (c) was for, and the search requirement is what makes it more than
a consolation prize: the free-text value is genuinely findable, just not filterable.

## Options Considered

### Option A: One vocabulary, `field_tag` points at an ordinary tag (chosen)

**Pros:** tier 2 works; one table, one mental model; a post tagged `fintech` is discoverable
by a fintech-field user immediately, with no mapping to maintain. Follows through on the
argument `data-model.md` §2.1 already makes for tags and interests sharing a table.
**Cons:** the onboarding field picker and the post tag input draw from the same pool, so a
curated-only filter (`is_curated=True`) is needed on the picker. One extra `WHERE` clause.

### Option B: Keep `kind`, add a Field → Tags mapping table

**Pros:** keeps field tags out of the tag cloud entirely; allows one field to map to many
topics ("software" → `web`, `mobile`, `devops`).
**Cons:** a whole extra table and an extra join in the Home query to solve a problem created by
a column we chose to add. Someone has to author and maintain the mapping, and it goes stale
silently. Over-engineered for ~15 fields.

### Option C: Give `Post` its own `field_tag` foreign key

**Pros:** tier 2 becomes a direct indexed lookup with no join through `PostTag`.
**Cons:** one more required question in the post composer, on a form that already asks for
title, body, tags, roles, stage, commitment and location. The spec's post fields (§4.2) do not
include a field, and adding a mandatory question to reduce a join is the wrong trade.

## Trade-off Analysis

Option A wins on the thing that matters most here, which is not performance but **the number of
concepts a reader has to hold**. Tags, interests and fields being one table means the Home
cascade reads as one idea: *match the user's tags against the posts' tags, with different
sources for "the user's tags" at each tier.* Options B and C both introduce a second kind of
topic identity, and a second kind of anything is where the next silent mismatch comes from.

The general lesson, recorded because it nearly cost a feature: **a column that partitions a
table into sets that must never mix will eventually be asked to make them match.** `kind` was
added for a display concern (keeping the tag suggestions clean) and quietly acquired a
semantic role it could not support. `is_curated` solves the display concern without partitioning
anything.

## Consequences

**Easier**
- Home tier 2 is a real, indexed, non-empty query.
- One vocabulary to seed, one to test, one to explain.
- A user whose field is `crochet-and-craft` sees craft posts on day one with zero follows —
  which is the entire point of `product-spec.md` §2.6, *value before the graph*.

**Harder**
- The onboarding field picker must filter to `is_curated=True`, or it will offer every
  user-invented tag as a "field".
- The ~15 curated field tags must be seeded in a data migration, not created ad hoc, or
  `field_tag` points at rows that differ per environment.
- QA's seed corpus has to draw post tags from a pool that *includes* the curated field tags,
  otherwise tier 2 is untestable in the demo — the bug reappears as a data problem instead of a
  schema one.

**Revisit if**
- Fields and topics genuinely diverge in practice (e.g. nobody tags posts `software` because
  it is too broad). The fix then is Option B's mapping table, which stays available.

## Action Items

1. [x] Remove `kind` from `Tag` in `docs/data-model.md` §2.1
2. [ ] Architect: data migration seeding ~15 curated field tags + ~40 curated roles
3. [ ] Architect: `Post.custom_roles` and `Profile.custom_skills` array fields, capped at 3
4. [ ] Discovery seat: include `custom_roles` in `search_vector` at weight B; **exclude** it
   from the role filter
5. [ ] Accounts seat: onboarding field picker filters `is_curated=True`
6. [ ] QA: seed corpus must tag a meaningful share of posts with curated field tags, and
   `test_home_cascade` must assert **tier 2 specifically returns rows** — not merely that Home
   is non-empty, which tier 3 would satisfy while hiding this exact bug
