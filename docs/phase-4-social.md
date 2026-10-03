# Phase 4 — Social: what shipped, and what other seats need to know

**Seat:** Builder · **Phase:** 4 (roadmap §Part 2) · **Status:** comments, sparks, saves and
in-app notifications all written. **Nothing has been run** — see §5.

`docs/` is the only shared memory (`CLAUDE.md` rule 1), so everything here is something another
seat can trip over. The schema reasoning behind all of it is `docs/review/social.md` — that
review remains the reference for this area.

---

## 1. Contracts other seats must honour

### 1.1 Never write an engagement row directly

`social/services.py` owns every write that moves a counter — the same contract
`accounts/services.py` holds for `Follow` and `Block`:

| Call | Instead of |
|---|---|
| `toggle_post_spark(user, post)` | `PostSpark.objects.create(...)` |
| `toggle_comment_spark(user, comment)` | `CommentSpark.objects.create(...)` |
| `toggle_save(user, post)` | `SavedPost.objects.create(...)` |
| `add_comment(author, post, body)` | `Comment.objects.create(...)` |
| `soft_delete_comment(comment)` | setting `Comment.deleted_at` |

Two rules are implemented there once, because they are the ones everybody forgets:

1. **A counter moves only when a row was actually created or actually deleted** (S3). A
   `delete()` returning 0 and a caught `IntegrityError` are both no-ops for the counter.
2. **Every decrement is `Greatest(F(field) - 1, 0)`.** These are `PositiveIntegerField`s, so a
   decrement against an already-drifted zero is an `IntegrityError` and a 500 on the button.

Each toggle also catches `IntegrityError` in a nested `atomic()` and treats it as "already on".
The `exists()`-then-`create()` version loses the double-tap race, which on a phone is a 500 on
the signature control of the product.

### 1.2 Soft-deleting a comment goes through `soft_delete_comment()` (S12)

**Trust & Safety and Django admin: this one is aimed at you.** Setting `deleted_at` by hand
leaves `Post.comment_count` one too high, so the post reads "12 comments" above 11 rendered
rows — a bug that looks like caching and isn't, appearing only in moderated threads.

### 1.3 A comment revives its post; a spark does not

`add_comment()` calls `Post.touch_activity()`, which is the only writer of `last_activity_at`
and the only thing that clears `is_stale` and `nudged_at`. Sparks deliberately do **not**
(TS-6): a spark is a stranger's one click and says nothing about whether the author is still
looking, which is the only question the nudge asks. Left in, any passer-by could keep a dead
post alive forever.

### 1.4 Comment counts: which number goes where

`data-model.md` §7.2 — counters are global, lists are block-filtered, so the two legitimately
disagree and must never appear on the same screen:

| Surface | Renders |
|---|---|
| Feed card, profile, landing teaser | `post.comment_count` (denormalised) |
| Post detail — heading **and** sticky bar | `comments|length`, the thread actually rendered |

Post detail previously rendered `post.comment_count` in the sticky bar while the thread above it
was filtered. It now renders the list length in both places, kept in sync by an out-of-band
HTMX swap on `id="post-comment-tally"`.

This is also why the thread is **unpaginated** (S13): paginate it and the heading says "8
comments" above 8 of 40, making visible exactly the artefact ADR-0002 resolved.

### 1.5 Comment reads go through `social.queries.visible_comments()`

`post.comments.all()` is not block-filtered. `posts.views.detail` was prefetching
`comments__author__profile`, which rendered a blocked person's comments in full on a page whose
every other element respected ADR-0002. One helper now does the block filter, the per-viewer
`is_sparked` annotation (one `EXISTS` for the thread, not one query per row) and the
oldest-first ordering that matches `comment_post_idx`.

---

## 2. Endpoints

All POST-only, all login-required, all `visible_to()`-filtered — the card for a blocked author's
post is never rendered, but `/s/spark/41/` is guessable. **404, never 403**: a 403 confirms the
row exists.

| Route | Name | Returns |
|---|---|---|
| `/s/spark/<pk>/` | `social:spark` | `components/_spark.html` |
| `/s/save/<pk>/` | `social:save` | `components/_save.html` |
| `/s/post/<pk>/comment/` | `social:comment_create` | the comment section |
| `/s/comment/<pk>/delete/` | `social:comment_delete` | the comment section |
| `/s/comment/<pk>/spark/` | `social:comment_spark` | `social/_comment_spark.html` |

Every one of them redirects to `<post>#comments` when the request did not come from HTMX, so the
comment form is a plain HTML form that happens to be enhanced.

**The public demo accounts get a real 403 on comment** (`data-model.md` §1.1.1), and spark and
save deliberately succeed. The form is hidden for them too, with the reason stated — a hidden
button is not a permission, but an enforced permission with no explanation is not a product.

---

## 3. Notifications

The `Notification` model and `notifications/migrations/0001_initial.py` are the **Architect's**
(commit `3f86bc3`). Everything else below is this seat's.

### 3.1 `notifications/services.py` is the only place a row is written or deleted

| Call | When |
|---|---|
| `notify_new_comment(comment)` | from `social.services.add_comment()` |
| `notify_new_follower(follower, following)` | from `accounts.services.follow()`, only on a real new edge |
| `drop_for_comment(comment)` | from `social.services.soft_delete_comment()` |
| `drop_for_post(post)` | **Posts & Feed: call this when you wire post deletion** |
| `drop_between(a, b)` | from `accounts.services.block()` |
| `mark_all_read(user)` / `unread_count(user)` | the Alerts screen and the bell |

Everything there is a no-op rather than an error when there is nothing to do. Fan-out hangs off
an action that has already succeeded — the comment is written, the edge exists — so a
notification that cannot be created must never take the action down with it.

**Sparks and saves notify nobody** (§2.7). Spec §4.6 lists exactly three triggers and sparks is
not among them, deliberately: a spark is a stranger's one click, and spark notifications are
noise. There is a test asserting the silence, because this is the kind of thing a later seat
"fixes".

### 3.2 The two dedup rules are not the same shape, and that is the point

- **Comments (rule 1):** no second `new_comment` for the same post from the same actor within
  60 seconds. A **double-submit guard, not a burst guard** — five comments over an hour is five
  things to read. There is no constraint underneath it, because the condition is a time window
  rather than a state; two requests 200ms apart can both pass. That is the accepted ceiling.
- **Follows (S5, ruled by Jeni 3 Oct 2026):** no second **unread** `new_follower` from the same
  actor — bump the existing row. This one *is* backed by a partial `UniqueConstraint`, so the
  fan-out is update-first, create-on-zero-rows, catch-`IntegrityError`-and-re-update.

**"Mark all read" is the dedup reset.** Both rules key on `is_read=False`, which is why opening
the Alerts screen deliberately does *not* mark anything read — auto-reading on view would stop
repeat follows ever collapsing.

**Bumping `created_at` only works through `QuerySet.update()`** (the S4 footgun). The field is
`auto_now_add`, which is ignored on UPDATE, so a `.save()`-based bump silently does nothing and
the collapsed notification sorts to the *bottom* of the bell.

### 3.3 The bell badge

`notifications/context_processors.py::unread_alerts` puts the count in every template's context,
registered by the Architect in `config/settings/base.py`. **It returns an empty dict for
anonymous visitors before any I/O** — the public feed and landing page are the most-hit queries
in the app and `CLAUDE.md` rule 7 makes them non-negotiable, so they must not acquire a count
query just because a context processor exists.

### 3.4 What is deliberately absent

`new_message` and the `conversation` FK are not in the model or `kind`'s choices: `messaging`
0001 cannot be finalised while Jeni's decision E is open, so there is nothing to point an FK at.
`notification_kind_targets` is what stops a `new_message` row being written in the meantime, and
`templates/notifications/_row.html` has no case for one. All three land together in
`notifications` 0002.

**S6 has never been ruled on.** The rule 1 / rule 2 asymmetry above is this seat's reading of
§5.2. If the answer is "collapse comment bursts too", the fix is a second partial
`UniqueConstraint` and a 0003 — not a change to the 60-second constant.

---

## 4. Requests for other seats

**Designer** — two template changes landed in your area, both minimal:

1. `components/_save.html` is **new**, extracted verbatim from the save button that was inline
   in `_post_card.html` (same classes, same aria, same icon call). The endpoint previously
   answered 204 No Content — "make no swap" — so the bookmark saved but the icon stayed hollow
   until the next full page render. `_post_card.html` now includes it. Worth a row in
   `design-system.md` §4's component index.
2. `social/_comment_spark.html` is a **comment-sized Spark**, deliberately kept out of
   `components/` until you have looked at it. It follows every §4.4 rule, with two differences
   for a control that appears a dozen times in a thread: a 16px icon with `text-xs`, and the
   44px target as height only rather than a wide pill. The v1 mockup drew it at `h-8` in brand
   green — both pre-date §7's 44px floor and the rule that burnt orange is Spark's alone. If you
   want the quieter green back, that is a §4.4 amendment rather than a local override.

**DevOps** — `[tool.ruff.lint.isort].known-first-party` in `pyproject.toml` lists every app
except `social`, which did not exist when the list was written. Ruff infers it from `src`, so CI
should pass either way; adding the word removes the doubt. That section is yours, so it is a
request rather than a change.

**Posts & Feed** — `posts.views.detail` resolves the post through `_feed_queryset()`, which
filters `status=looking`. So a `team_formed` or `closed` post 404s on its own detail page, while
the mockup's Saved screen shows a "Team formed" card you can tap. Commenting on one works (the
social endpoints filter on `active()`, not status), so the two disagree. Not touched here
because it is a status-semantics decision, not a Social one.

**Designer / Posts & Feed** — `_post_card.html` links `post.author.get_absolute_url`
unconditionally, but an anonymised author's profile 404s (`accounts/views.py`). `social/_comment.html`
renders `[deleted]` as plain text for that reason; the card still produces a dead link.

---

## 5. Tests

Three files under `tests/social/`:

- `test_comments.py` — the counter rules, the `touch_activity` bump, the double-delete no-op,
  the 404s in both block directions, the demo account's 403, and the two-rule case where a
  comment's author is visible but the post's author is not.
- `test_engagement.py` — both toggles, `save_count`, the `Greatest(…, 0)` floor, and the proof
  that a spark does **not** revive a post.
- `test_notifications.py` — both triggers, both dedup rules (including the 60-second boundary
  in each direction), the silence on sparks, S8's deletes, and the bell emptying in both block
  directions.

**None of it has been run.** This machine has no Python environment, no Django and no Postgres —
`import django` fails and there is no container runtime — so nothing in Phase 4 has executed,
including the hand-written `notifications` 0001. Every file byte-compiles and every template's
tag nesting balances; that is the whole extent of the verification. The first `migrate` and the
first `pytest` run against a real database are the real check, and CI's
`makemigrations --check` drift gate is the first thing likely to flag the hand-written
migration — if it does, expect a serialization nit rather than a schema difference.

---

## 6. Still open

- **S6 needs Jeni's ruling** — see §3.4. It is the one decision in this phase that was acted on
  without one, and the code and the test both say so out loud.
- **`notifications` 0002** is blocked on decision E (unread dot or number). That one answer
  unblocks `messaging` 0001, the `conversation` FK, the `new_message` kind and the S4 unread-DM
  unique constraint, in one pass.
- **The Saved screen** (screen 13) — the save toggle and `save_count` work; the screen that
  lists them is not built. It is also second on the roadmap's cut list, so this may be the right
  place to leave it.
- **Marking a single notification read** — the only control is "Mark all read", which is all the
  mockup drew. Tapping a row navigates but does not clear it, so the badge only drops on the
  explicit action.
- **`components/_empty_state.html` is being called with the wrong parameter names** in
  `posts/feed.html` (`cta_label` / `cta_href` instead of `action_label` / `action_url`), so the
  one way out of the empty feed never renders. Pre-existing, found while writing the Alerts
  empty state, and in the Designer's and Posts & Feed's area rather than this one.
