# Phase 6 — Trust & jobs: what shipped

**Seat:** Builder · **Phase:** 6 · **Date:** 4 Oct 2026

The `Report` model, the `demo_moderator` Group and the admin queue are the **Architect's**
(commit `1f77d41`) — see `docs/data-model.md` §6. Everything below is the Builder seat's.

---

## 1. Reporting

`/report/idea/<slug>/`, `/report/comment/<pk>/`, `/report/user/<username>/`. One form, three
targets.

**Signing in is required** (Decision H, Jeni, 3 Oct 2026) — not to raise the barrier to
flagging real abuse, but because the anti-brigading constraint is "one *unresolved* report per
person per target" and it needs a person to key on.

Two things in `moderation/views.py` that look like details and aren't:

1. **`IntegrityError` is the normal path, caught in a savepoint.** Reporting something twice
   fires `uniq_open_report_per_*`, which is the constraint doing its job. It is caught rather
   than pre-checked, because check-then-insert is a race that two taps on a phone will lose —
   and it is caught **inside a nested `transaction.atomic()`**, because Postgres marks the
   whole transaction unusable after a constraint violation, so catching it outside a savepoint
   turns the next query, including rendering the response, into a
   `TransactionManagementError`. That bug was written, caught by a test, and fixed.
2. **`target_snapshot` is written once, at report time** (TS-3, ruled in by Jeni 3 Oct 2026).
   Posts and comments are editable, so without it somebody can post something abusive, get
   reported, and edit it innocuous before a moderator looks — leaving them ruling on content
   that no longer exists. It cannot be back-filled, which is why it had to be decided before
   the demo had real content.

"Other" is the one conditionally-required field: a queue full of bare `other` with no text is a
queue nobody can work, and the moderator cannot ask the reporter.

---

## 2. Rate limiting

`moderation/limits.py` holds the whole policy. Spec §4.7 names posts, DMs and follows;
**reports are added** at the Trust & Safety seat's request — the unique constraint stops
duplicate reports of one target, but one account can still flood the queue with fifty
different ones, and that is a moderation denial-of-service with no other defence.

| Action | Limit |
|---|---|
| Publish an idea | 10/h |
| Comment | 30/h |
| Follow | 60/h |
| Report | 20/h |
| Send a DM | 60/h *(wired when messaging lands)* |

All keyed on `user`, which every rate-limited action can do because every one of them is
login-required — and which sidesteps the shared-proxy-IP problem Render introduces (TS-9).

**⚠ The rates themselves have not been ruled on.** They are the Builder seat's numbers, set
generous enough to catch a script and never a person. One file to change them in.

### The production risk this closes

`trust-safety.md` §2 raised it as a "whole site 500s" risk rather than a "one feature degrades"
one: `render.yaml` does not guard `REDIS_URL`, `CACHES["default"]` is Redis in production, and
django-ratelimit reads the cache on **every** post, comment, follow and report. An unreachable
Redis would therefore 500 every write path in the product.

`rate_limit()` wraps the library's check and **fails open**, logging the exception. The cost of
letting a spammer past during a Redis outage is some spam; the cost of failing closed is that
nobody can post, comment, follow or report at all, for a reason invisible in the traceback.

A real limit raises `Ratelimited`, which `config.views.permission_denied` turns into **429 with
`Retry-After`**, not Django's default 403. A 403 means "not allowed"; this is "not allowed
*yet*", and 429 is the only form of that a client can act on.

---

## 3. The stale-post nudge

`moderation/tasks.py`. Spec §4.8's anti-ghosting countermeasure, and the state machine the
Trust & Safety review asked for after finding `is_stale` had "three fields and zero rules":

| From | When | Effect |
|---|---|---|
| fresh | quiet 30 days, still `looking`, not deleted | send a `stale_nudge`, set `nudged_at` |
| nudged | 7 more days of silence | `is_stale=True` |
| nudged or stale | any `last_activity_at` bump | `is_stale=False`, `nudged_at=NULL` |

The third row is **not this job's work** — it is `Post.touch_activity()`, called on comment and
on author edit, which is why nothing in the job ever un-stales anything.

Four rules the job holds to:

- **It never touches `status`.** Q4 made `is_stale` (the system's judgement) and `status` (the
  author's choice) separate fields precisely so the system cannot overwrite what the author
  said. A job that helpfully closed a stale post would undo the whole reason for that split.
- **Stale ranks lower, never hides** (Q4). The post stays in the feed and stays searchable.
- **Sparks are not activity** (TS-6). Otherwise any passer-by keeps a dead post alive with one
  click.
- **Nudge before demote.** Reversed, every post that crossed both thresholds between two runs —
  which is every post, the first time this runs against a seeded database — would be demoted
  without ever being asked, and the asking is the entire feature.

**⚠ The 30/7 thresholds are the Trust & Safety seat's proposal (TS-8/TS-9) and have not been
ruled on either.** Named constants at the top of the module.

Delivery is the `stale_nudge` notification kind (TS-2 / Designer GAP 13) — the one kind with no
actor, because nothing did it, the system noticed. It needs no dedup constraint: the job's own
candidate query filters on `nudged_at IS NULL`, so that is the guard.

### How it runs

`POST /internal/cron/stale-post-nudge/` with an `X-Cron-Key` header, hit by
`.github/workflows/cron.yml` on a daily schedule. **Not Celery Beat**: Render's free tier has no
always-on worker, and a beat process inside the free web service would be asleep most of the
time and silently miss its schedule (`deployment.md` §4). The cron request also wakes the app.

The endpoint answers **404, not 403**, on a bad or missing key — a 403 confirms the endpoint
exists and that the key was merely wrong, which is a free oracle for anyone probing
`/internal/`. The key is compared with `hmac.compare_digest`, because `==` short-circuits on the
first differing byte and leaks the secret to anybody willing to time a few thousand requests.
An unset `CRON_SECRET` refuses everything: a misconfigured deploy should mean a job that does
not run, not an open endpoint.

**DevOps:** `CRON_SECRET` and `RENDER_URL` need to exist as repo secrets and as a Render env
var before the workflow does anything — it exits 0 and skips without them.

---

## 4. Tests

`tests/moderation/test_reports.py` and `test_stale_nudge.py` — 30 tests. The constraint in both
directions (same target twice collapses; a dismissal lets you report again; two people can
report the same thing; one person can report two different things), the snapshot surviving both
an edit and a deletion, the whole state machine including the spark-is-not-activity case, and
the cron endpoint's three refusal paths.

---

## 5. Still open

- **The rate numbers and the 30/7 nudge thresholds** both need a ruling, as above.
- **TS-5 `Report.action_taken`** (`none` / `content_removed` / `user_warned` / `user_suspended`)
  was not shipped — the Trust & Safety review itself calls it the first thing to cut. The cost
  is that "has this account been warned before?" is a free-text search through
  `resolution_note`.
- **Moderation has no custom UI and does not need one** in v1. Django admin plus `status`,
  `resolution_note` and `reviewed_by` is the whole queue (§6.1).
