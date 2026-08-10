# Data-model review — Designer seat

**Reviewer:** Designer · **Date:** 7 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock)
**Method:** low-fidelity wireframes of all 14 screens in `roadmap.md` §1.2, each element
annotated with the model field behind it. Wireframes: `design/wireframes/v6-lofi-all-screens.html`

**Headline:** the model holds up well. I found **15 things**, and only **three are schema
changes I'd argue must land before lock**. Two more are product decisions only Jeni can make.
The rest are contracts, doc alignment, or my own design debt.

The three-schema-change list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **11** | `Conversation.origin_post` | Core loop is "find idea → message author". Cannot be back-filled later |
| **13** | A `stale_nudge` notification kind | The anti-ghosting feature has a trigger but no delivery channel |
| **12** | `Conversation.last_message_sender` | Conversation list can't render "You:" without a join that defeats the denormalisation |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a field/choice before lock. Expensive or impossible to retrofit |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but an interface all seats depend on and nobody has written down |
| ⚪ **Mine** | Design debt on my side. Listed so it's visible, not to create work for the Architect |

---

## 1 · Findings

### 🔴 GAP 11 — `Conversation` has no link to the idea it started from

**The product is "find an idea → message the person."** Anyone can DM anyone with no request
gate (spec §2.2), so the receiver's first question is always *why is this person messaging me*.
Every messaging screen I've drawn answers it with a context strip: **"About: An app that moves
leftover canteen food to hostels…"**

`Conversation` has `dyad_key`, `last_message_at`, `last_message_preview`, `created_at` — and no
reference to a `Post`.

```python
origin_post = models.ForeignKey(
    "posts.Post", null=True, blank=True, on_delete=models.SET_NULL,
    related_name="conversations_started",
)
```

Nullable because a DM started from a profile has no origin post. `SET_NULL` so deleting the idea
doesn't destroy the conversation — consistent with §8 keeping messages when everything else goes.

**Why now:** this is the one finding that genuinely cannot be retrofitted. Add it in September
and every existing conversation has `origin_post = NULL` forever, because the information was
never captured. Either the feature ships without history or it doesn't ship.

---

### 🔴 GAP 13 — the stale-post nudge has no way to reach the user

Spec §4.8 makes this one of three named anti-ghosting countermeasures: a post untouched ~30 days
"triggers *Still looking for teammates?*"; no response → auto-marked inactive and demoted.

The schema has the whole **trigger** side — `Post.is_stale`, `Post.nudged_at`,
`Post.last_activity_at`, and the ranking behaviour from Q4. It has no **delivery** side:
`Notification.kind` is exactly `new_message` / `new_follower` / `new_comment`. Email digests are
Phase 2. So the job can mark a post stale but cannot tell anybody.

Options, in my order of preference:

1. **Add `stale_nudge` to `Notification.kind`.** The existing nullable `post` FK already carries
   the target, and `actor` is nullable, which is exactly right for a system-generated row. One
   choice value.
2. Surface it only as a banner on the author's own post — but then the author must go looking
   for it, which is not a nudge.

If option 2 is the intent, it should be written down, because the wireframes and the spec both
read as "the user is told".

> Note: `CheckConstraint(recipient != actor)` is fine with a null actor — the constraint is only
> violated when both are set and equal. Worth confirming the implementation allows `actor=NULL`.

---

### 🔴 GAP 12 — conversation list can't tell whose message was last

The conversation list shows `You: Sent you the mockup — no rush` when the last message was mine.
`last_message_preview` is text only; there's no sender.

The stated reason for denormalising preview and timestamp onto `Conversation` is that "the list
renders with zero joins" (§4.1). Joining to `Message` just to find the sender gives that back.

```python
last_message_sender = models.ForeignKey(
    settings.AUTH_USER_MODEL, null=True, blank=True,
    on_delete=models.SET_NULL, related_name="+",
)
```

Written in the same transaction as the other two denormalised fields. Small, and it's cheap to
add now versus a data migration recomputing it across every conversation later.

---

### 🟠 GAP 1 — where does `username` come from, and can it change?

`User.username` is unique, indexed, validated `[a-z0-9_]{3,30}`, has a reserved-name blocklist,
and **is the public URL** (`/u/<username>`). The sign-up screen collects name, email, password.
It does not collect a username.

§10 describes an allauth adapter normalising usernames — but only for **Google sign-in**. v1 is
email/password, so that path doesn't cover us.

Two questions, both product:

1. **Ask or derive?** Asking means a fourth field plus a live availability check (an endpoint,
   and a debounce — real work for Accounts). Deriving from the email is invisible but produces
   things like `dev_krishnan_91`, which people then want to change.
2. **Is it changeable?** Not answered anywhere. If yes, old profile URLs rot and Settings needs
   a screen — I've drawn a placeholder for it. If no, the sign-up screen has to be the moment it
   is chosen, which argues for asking.

My preference: **derive silently at sign-up, allow one change in Settings**, accept URL rot (we
have no inbound links to protect yet). But this is Jeni's call and it changes two screens.

---

### 🟠 GAP 8 — is a person's spark history public?

I put a **Sparked** tab on other people's profiles. `PostSpark` carries
`Index(user, -created_at)`, so the query is cheap and clearly anticipated — but nothing states
whether one user may see another's sparks.

This is a privacy decision, not a schema one, and it needs answering before Social builds the
tab. Safe default: **sparks public, saves private** — a spark is already a public signal that
ranks the feed, whereas a save is a private bookmark. `SavedPost` is correctly own-only in my
designs either way.

---

### 🟡 GAP 3 — `is_sparked` / `is_saved` per-viewer annotations aren't specified

Every feed card renders whether *this viewer* has sparked and saved the post. Correctly, neither
is a column — they're `PostSpark` / `SavedPost` rows. But nothing in the model says the feed
query must **annotate** them.

Left unstated, the obvious implementation checks per card, which is an N+1 on the most-hit query
in the app, and it will be written that way by more than one seat because six seats can't see
each other's chats.

This deserves the same treatment `visible_to()` got in §1.6 — one named method, used identically
everywhere:

```python
Post.objects.visible_to(request.user).for_viewer(request.user)
# adds is_sparked / is_saved via Exists(), one query
```

Anonymous should short-circuit to `False` for both without touching the database, the same way
`visible_to()` no-ops.

---

### 🟡 GAP 4 — the Home cascade needs to say which tier each post came from

The cold-start Home is the most consequential screen in the product, and the design labels each
band with its source: *from people you follow* → *because you picked android* → *newest overall*.
Unlabelled, a new user's Home is an unexplained list of strangers, which is exactly the
cold-start failure §4.3 exists to prevent.

The cascade is defined as three queries. Nothing says the result carries a **marker of which tier
produced each post**. Discovery can return three tagged querysets or annotate a constant — either
is trivial *if decided now*, and awkward once the view is written and paginating over a union.

Not necessarily a schema change. It is an interface contract, and it belongs in §3 next to the
cascade table.

---

### 🟡 GAP 10 — search match highlighting is undefined

Search results show the matched term highlighted inside the excerpt. That needs Postgres
`ts_headline()` or client-side highlighting; neither is mentioned. Minor, and it's fine to
declare it out of scope — but a search result that gives no visible reason for matching is a
poor result, and Discovery should know either way.

---

### ⚪ GAP 5 — `PostRole.note` has no UI

`CharField(120)`, e.g. "React dev, ~5 hrs/week". It's a genuinely good field — the difference
between "Android dev" and "Android dev, evenings, ~5 hrs/week" is most of what a joiner needs to
self-select. **Nothing in my designs displays it, and my create form doesn't capture it.**

Flagged so the Architect doesn't ship a column nobody writes to. I want to keep it; I'll design
both the input and the display.

### ⚪ GAP 7 — `PostImage.caption` is never captured

Same shape. The column exists, no form field writes to it. Keep it — a caption is often the only
text an image ever gets, and it's the accessible description too. I'll add the input.

### ⚪ GAP 9 — `Profile.work_done` has no design

`TextField(1000)`, straight from spec §4.1. My profile screen never rendered it. It's the field
that answers "has this person actually finished anything", which is the main thing a joiner is
trying to work out. I'll design it in.

### ⚪ GAP 6 — I drew a "Save draft" button and drafts don't exist

§2.3.1 is explicit: **no drafts in v1**, a post is live when created. My v5 create screen had a
"Save draft" control. My error, caught by this sweep, now removed.

Recording it because had it shipped, someone would reasonably have built a draft state to satisfy
the button — which is a schema change arriving through a mockup rather than through this process.

### ⚪ GAP 15 — `[deleted]` users need a visual design on five surfaces

§8.1 requires every seat rendering a user to handle the `[deleted]` placeholder: feed cards,
comments, conversation headers, notifications, profile. That's a real visual state and I haven't
drawn it. Mine to fix — listed because it's a cross-seat consequence of ADR-0001 that's easy for
everyone to assume someone else owns.

### ⚪ Missing screen — report / block flow

The ⋯ menus in my designs go nowhere. `Report` is complete (`reason` × 6, `details`,
conditional unique constraints) — the **screen** doesn't exist. Block needs a confirm step
explaining it's mutual and hides existing chat (ADR-0002). Mine.

---

### 🟡 GAP 2 — onboarding can't be resumed

`Profile.onboarding_completed_at` is null-or-set: it records *finished*, never *how far*. A user
who abandons on step 2 can't be resumed, and "skipped everything" is indistinguishable from
"never started" — which also means we can't measure where people drop out.

All steps are skippable so this may be an acceptable simplification. If so it should be a
recorded decision rather than an accident; if not, one nullable `onboarding_step` smallint covers
it.

---

## 2 · Per-screen field inventory

Everything each screen needs. Unmarked = exists in the model.

| # | Screen | Fields required |
|---|---|---|
| 1 | Landing | `Post.title/published_at/spark_count/comment_count` · `User.display_name` · `Profile.headline/avatar_display_url` · `PostRole→Role.name` · `User.is_public_demo` · demo password *(settings const, correctly not schema)* |
| 2 | Sign up / log in | `User.email/password/display_name` · **`User.username` — GAP 1** |
| 3 | Onboarding | `Profile.purpose/occupation/field_tag` · `Tag.is_curated` *(field picker is curated-only)* · `ProfileInterest⇄Tag` · `Follow` · `Profile.onboarding_completed_at` · **resume position — GAP 2** |
| 4 | Home | tier-1/2/3 cascade · `Profile.following_count/field_tag` · full card set (row 5) · **tier provenance — GAP 4** |
| 5 | Feed | `Post.title/body/stage/commitment/status/is_stale/city/is_remote_friendly/published_at/spark_count/comment_count` · `PostTag→Tag` · `PostRole→Role` + `Post.custom_roles` · `PostImage` · author `display_name`/`headline`/avatar · **`is_sparked`/`is_saved` — GAP 3** |
| 6 | Post detail | all of row 5 in full · `Comment.body/author/created_at/spark_count` · `CommentSpark` · `Follow` · `SavedPost` · **`PostRole.note` — GAP 5** · report screen missing |
| 7 | Create / edit | `Post.title/body/stage/commitment/city/is_remote_friendly/status` · `PostTag` · `PostRole` + `custom_roles` (max 3) · `PostImage` (max 5) · **`PostRole.note` — GAP 5** · **`PostImage.caption` — GAP 7** · no drafts (GAP 6) |
| 8 | Profile | `User.display_name/username` · `Profile.headline/bio/city/avatar/occupation/follower_count/following_count/post_count` · `github_url/portfolio_url/website_url` · `ProfileSkill→Role` + `custom_skills` · `Follow.note` · `SavedPost` *(own)* · **`work_done` — GAP 9** · **sparks public? — GAP 8** |
| 9 | Search | `Post.search_vector` · `Profile.search_vector` · `custom_roles`/`custom_skills` in vector · filters: `PostRole`, `commitment`, `city_slug` · result counts *(query)* · **highlighting — GAP 10** |
| 10 | Messages | `Conversation.last_message_at/last_message_preview` · `ConversationParticipant.user/last_read_at` · **`last_message_sender` — GAP 12** · `is_archived`/`is_muted` exist, no UI yet *(mine)* |
| 11 | Chat thread | `Message.body/sender/created_at` · `ConversationParticipant.last_read_at` · **`origin_post` — GAP 11** |
| 12 | Notifications | `Notification.kind/actor/post/comment/conversation/is_read/created_at` · **stale nudge kind — GAP 13** · **`Follow.note` unreachable — GAP 14** |
| 13 | Saved | `SavedPost.created_at` · `Post.*` · `Post.status` *(a saved post can go `team_formed` — show it, don't hide it)* |
| 14 | Settings | all `Profile.*` · `ProfileInterest` · `ProfileSkill` · `User.email` · `Block→blocked User` · `User.deletion_requested_at` · **username change — GAP 1** |

### 🟡 GAP 14 — follow notifications can't reach the note

A `new_follower` row has `actor` but no link to the `Follow` row, so it can't render
`Follow.note` — the one thing that makes a follow notification worth opening ("I'd want the
Android role"). Workable without a schema change by looking up
`Follow(follower=actor, following=recipient)`, but that's an extra query per notification and it
breaks silently if the follow is later withdrawn.

A nullable `follow` FK would match the existing concrete-nullable-FK-per-target-type pattern. Low
severity — I'd take the extra query if the Architect prefers fewer columns.

---

## 3 · Things I checked that are fine

Recording these so nobody re-reviews them:

- **Follow with a note** — `Follow.note` (200) exists and is exactly what the UI needs.
- **Stage / commitment / status as three separate concerns** — correct, and `is_stale` being
  system-controlled and separate from author-controlled `status` is the right split. Stale posts
  sinking rather than hiding (Q4) means the card needs a visual treatment for stale-but-visible;
  the field supports it.
- **Curated roles + free-text "Other" vs free-text tags** — the asymmetry (ADR-0004) is right and
  the create form reflects it: roles are a closed picker plus Other, tags are an open input.
- **Counters global, never viewer-relative** (§7.2) — the feed card renders the denormalised
  count and post detail renders the fetched list length. The two never co-occur in my designs.
- **Comments flat, deletable, not editable** — no `is_edited` needed, no `parent`.
- **Comment sparks in v1** — `CommentSpark` exists; my comment rows use it.
- **Max 5 images / max 3 custom roles** — form-level, matches the designs.
- **Search excludes comments** (Q11) — so no comments tab in search results. Confirmed absent.
- **Deletion copy** — my Settings screen says ideas stay, credited to a placeholder. Matches
  ADR-0001. I should also say **logging back in within 30 days cancels it** — I'd left out the
  reassuring half.
- **Anonymous `visible_to()` is a no-op** — the public landing/feed path stays cheap, which is
  what makes rule 7 affordable.

---

## 4 · What I need back

1. **Three schema changes** — GAP 11, 13, 12. My case for all three is above; 11 is the one that
   is genuinely irreversible.
2. **Two decisions from Jeni** — GAP 1 (username capture + changeability), GAP 8 (are sparks
   public).
3. **Three contracts written into the doc** — GAP 3 (`for_viewer` annotations), GAP 4 (tier
   provenance), GAP 2 (onboarding resume: decide, then record).
4. **Confirm you want to keep** `PostRole.note`, `PostImage.caption`, `Profile.work_done`
   (GAPs 5, 7, 9). If yes I design them in this week. If any are speculative, cutting them now is
   cheaper than a column nobody writes to.

Everything else in the model I'd build against as-is.
