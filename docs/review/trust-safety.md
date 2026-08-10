# Data-model review — Trust & Safety seat

**Reviewer:** Trust & Safety · **Date:** 8 Aug 2026
**Reviewing:** `docs/data-model.md` v1 (approved 31 Jul, pre-lock)
**Scope:** §6 `moderation` · `Post.is_stale` / `nudged_at` / `last_activity_at` (§2.3, §2.3.2) ·
rate limiting · the scheduled-job path (`deployment.md` §4, `.github/workflows/cron.yml`)
**Method:** walked the two features I own end to end against the schema — *file a report → Jeni
actions it in admin*, and *post goes quiet → nudge → demote → revive* — and wrote down every
point where the schema couldn't carry the next step.

**Headline:** §6 is close and two of its judgement calls are right. The problem is the other
half of my area: **`is_stale` has three fields and zero rules.** The transitions are undefined,
one missing default makes the feature invisible on the deployed demo, and the nudge has no
delivery channel. I found **13 things** — **5 are schema changes I'd argue must land before
lock**, 4 are decisions only Jeni can make, 4 are contracts or mine.

The schema-change list, up front:

| # | Change | Why it can't wait |
|---|---|---|
| **TS-1** | `Post.last_activity_at` needs `default=timezone.now` | Non-null, no default — and without it **no seeded post can ever go stale**, so §4.8 is undemonstrable |
| **TS-2** | `Notification.kind` needs a `stale_nudge` value | The nudge has a trigger and no way to reach anyone. *Same finding as Designer GAP 13* |
| **TS-3** | `Report.target_snapshot` | A reported post can be edited innocuous before review. Cannot be back-filled |
| **TS-4** | Add `X__isnull=False` to the 3 conditional unique constraints | They work today by accident of Postgres NULL semantics, not by design |
| **TS-5** | `Report.action_taken` | `status='actioned'` doesn't record *what was done*. Optional — cut it if you want minimal |

---

## Severity key

| | Meaning |
|---|---|
| 🔴 **Schema** | Needs a field/default/choice before lock |
| 🟠 **Decision** | Product question for Jeni. Schema may or may not follow |
| 🟡 **Contract** | No new column, but a rule other seats depend on and nobody has written down |
| ⚪ **Mine** | My implementation problem. Listed so it's visible, not to create work for the Architect |

---

## 1 · Findings

### 🔴 TS-1 — `last_activity_at` has no default, and that silently kills the demo

§2.3 lists `last_activity_at` as `DateTimeField, indexed` — non-null, no default, nothing that
sets it at creation. Two consequences, and the second is the one that matters.

1. Post creation fails without a default.
2. **The seed.** §2.3.1 exists specifically so `seed_demo` can write arbitrary `published_at`
   values and produce a realistic 90-day spread. If the seed sets a 90-day-old `published_at`
   but `last_activity_at` lands at *now*, then **not one of the ~45 seeded posts can ever go
   stale**, and the anti-ghosting feature — the countermeasure spec §4.8 calls the #1 killer in
   this category — is invisible on the deployed site.

It fails silently, with no error, exactly like `Tag.kind` in §9.1.

```python
last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)
```

**Also needs, via Jeni → QA:** the seed must set `last_activity_at` alongside `published_at`,
and should deliberately seed ~3 posts at `is_stale=True` so the demoted state is visible on day
one. Not a schema change, but it's the other half of this fix.

---

### 🔴 TS-2 — the nudge has no delivery channel

`Notification.kind` is exactly `new_message` / `new_follower` / `new_comment`. Email digests are
Phase 2 and the dev backend is console. **The job can mark a post stale but cannot tell
anybody.**

Add `stale_nudge` to `Notification.kind`. The nullable `post` FK already carries the target and
the nullable `actor` is right for a system row. Cost is zero — Django `choices` generate no DB
constraint, so it is a no-op `AlterField`.

> **Confirming Designer GAP 13, independently and by a different route** (they found it drawing
> screens, I found it walking the job). Two seats, same hole. I'm adopting **their** name,
> `stale_nudge`, over my earlier `post_nudge` so the Architect gets one name, not two.
>
> Also confirming their open question: `CheckConstraint(recipient != actor)` is **safe** with a
> null actor. In Postgres a CHECK fails only on `FALSE`; `recipient_id != NULL` evaluates to
> `NULL`, which passes. No constraint change needed.

The notification is what makes the nudge *arrive*. The in-place "Still looking for teammates?
Yes / No" control on the author's own post is what makes it *answerable* — that's Designer's,
and both halves are needed. Designer's option 2 (banner only) is not a nudge: the author has to
go looking for it.

---

### 🔴 TS-3 — a reported post can be edited innocuous before review

Posts are editable. Someone posts something abusive → gets reported → edits the title and body
into something harmless → Jeni opens the queue and reviews a report against content that no
longer exists, with no way to know it ever did.

Soft delete covers the *deletion* path well (§2.6 explicitly keeps a deleted comment attached to
an open report). Nothing covers the *edit* path.

```python
target_snapshot = models.TextField(blank=True)   # title + body, or comment body, at report time
```

One column, no index, written once at report creation and never updated. It is the difference
between an actionable queue and a guessing game, and it is impossible to back-fill — by the time
we notice we need it, the original text is gone.

---

### 🔴 TS-4 — the three unique constraints work by accident, not by design

The conditional constraint itself is **correct** and compiles to a Postgres partial unique index
(§9.1's post-mortem is right — see §3 below). This is about a different edge.

Postgres treats `NULL`s as distinct in a unique index. That's *why* three separate constraints
coexist: on a user-report, `post IS NULL`, so `(reporter, post)` never collides. Nobody wrote
that down, and Django 5.1+ ships `UniqueConstraint(nulls_distinct=False)`. The day someone sets
that flag — reasonably, thinking they're tightening things — **every user-report in the system
collides on `(reporter, NULL)` and only one person can ever report anyone.**

Make the dependency explicit rather than load-bearing-and-invisible:

```python
UniqueConstraint(
    fields=["reporter", "post"],
    condition=Q(status__in=["open", "reviewing"], post__isnull=False),
    name="uniq_open_report_per_post",
)
# and the same shape for comment / reported_user
```

Costs nothing. Removes the trap.

**Implementation note while the Architect is in there:** on Django 5.2 `CheckConstraint` takes
`condition=`, not the deprecated `check=` (renamed 5.1, removed in 6.0). Relevant to the
"exactly one of `reported_user` / `post` / `comment` is non-null" constraint, which needs the
explicit three-way OR — there's no count-style shortcut in Django.

---

### 🔴 TS-5 — `status='actioned'` doesn't say what was done *(optional)*

`status` + `resolution_note` + `reviewed_by` records **that** a report was actioned, not
**what** we did. That matters the second time the same account is reported: "has this person
been warned before?" is currently a free-text search through `resolution_note`.

```python
action_taken = models.CharField(max_length=20, choices=..., blank=True)
# none / content_removed / user_warned / user_suspended
```

Listed as 🔴 because it's cheapest now, but it is the **one item on this list I'd cut first** if
the Architect wants to hold the line on scope. §6's "no `ModerationAction` model in v1" is right
(see §3); this is one column, not a model.

---

### 🟠 TS-6 — `last_activity_at` must not be bumped by sparks

§2.3 says `last_activity_at` is "bumped by spark/comment/edit." **Sparks have to come off that
list.**

If a spark resets staleness, any stranger keeps a dead post alive with one click, and a
two-person ring can farm the top of the feed deliberately. A spark is a one-click reaction from
someone who isn't the author — it says nothing about whether the author is still looking, which
is the only question the nudge asks.

> **Proposed:** `last_activity_at` is bumped by **author edit · new comment · the author's
> explicit "yes, still looking"**. Not sparks, not saves.

No schema change — a correction to §2.3 and a rule other seats follow. **Cross-checked before
proposing it:** nothing else reads `last_activity_at`. §2.3.2's feed sorts on `published_at` and
`spark_count`; the only index on it (`Index(-last_activity_at)`) is labelled "the stale-post
nudge job". So this field is effectively mine alone, and narrowing it breaks nothing. If
Discovery later wants a spark-inclusive recency signal, that is a second field, not this one.

---

### 🟠 TS-7 — what clears `is_stale`? (Jeni's explicit question)

**Not only the button.** The explicit "yes" is how a *silent* post gets revived. But if a post
gets a real comment and the author replies, it is demonstrably alive — refusing to un-stale it
because nobody clicked a button makes the Feed lie, which is the exact failure this feature
exists to prevent.

> **Proposed:** any `last_activity_at` bump (as narrowed in TS-6) clears `is_stale`. The button
> is just the cheapest bump when nothing else has happened.

---

### 🟠 TS-8 — how long is the grace period, and does the nudge repeat?

Spec §4.8 says "no response → auto-marked inactive" with no number, and the schema has
`nudged_at` with no stated meaning beyond "last nudge sent."

> **Proposed:** 30 days quiet → nudge. **7 days** more with no response → `is_stale=True`.
> **One nudge only** — re-nudging a post nobody has touched in two months is spam from us.

Jeni's numbers. I need them before I write the task.

---

### 🟠 TS-9 — can an anonymous visitor file a report?

Public read is non-negotiable (rule 7), so anonymous users can see reportable content.
`reporter` is nullable, so the schema currently permits an anonymous report — and if we allow
one, **the anti-brigading constraint stops working entirely** (all-NULL reporters never collide)
and rate limiting falls back to IP, which behind Render's proxy may be a single shared key.

> **Recommendation: reporting requires sign-in.** Rule 7 names post / follow / spark / comment /
> DM as the gated actions and doesn't mention report either way, so this is Jeni's call.

Worth stating precisely for the record: under ADR-0001 a `User` row is never hard-deleted
(deletion anonymises), so `SET_NULL` on `reporter` will in practice **never fire**. The
constraint is sound today and would quietly stop being sound the day anonymous reporting is
allowed. That's the whole risk — not the nullable FK itself.

---

### 🟡 TS-10 — the `is_stale` state machine, written down

The schema has the fields; nobody has written the transitions. This is the contract QA tests
against and Posts & Feed builds the Yes/No control against. Recording it here so it exists;
it lands in `docs/` properly once TS-6 → TS-9 are ruled on.

| From | Trigger | To |
|---|---|---|
| fresh (`is_stale=F`, `nudged_at=NULL`) | `last_activity_at` < now − 30d, `status='looking'`, `deleted_at IS NULL` | send `stale_nudge`, set `nudged_at=now` |
| nudged | no activity for 7d after `nudged_at` | `is_stale=True` |
| nudged **or** stale | any `last_activity_at` bump (TS-6) | `is_stale=False`, **`nudged_at=NULL`** |

**`nudged_at` must be cleared on revival.** This is the part that isn't obvious and isn't
anywhere in the doc: without it, a post gets exactly **one** nudge in its entire life. Revived in
month 2, abandoned in month 3 → never nudged again, silently. The schema already allows it
(`nudged_at` is nullable); the rule simply doesn't exist yet.

The job never touches `status`. Q4 already settled that `is_stale` and `status` are separate so
the system can't overwrite the author's choice — TS-10 is the rule that keeps that promise
concrete.

---

### 🟡 TS-11 — the demotion job's index is adequate, but the cheap version is free right now

§2.3.2 gives `Index(-last_activity_at)` for the job. Direction is a non-issue — Postgres scans a
btree backwards — but it's not partial, so the job walks rows that are soft-deleted, `closed`,
`team_formed`, or already stale.

At v1 scale (~45 posts, thousands eventually) **this is fine and I'm not asking for it on
performance grounds** — that would contradict §2.3.2's own "don't denormalize until `EXPLAIN`
says so", which I agree with. I'm only noting that a partial index is free *before* lock and a
migration *after*:

```python
Index(fields=["last_activity_at"],
      condition=Q(deleted_at__isnull=True, is_stale=False, status="looking"),
      name="post_stale_candidates_idx")
```

All three predicates are immutable, so it's a legal partial index. **Architect's call — take it
or leave it.** No objection either way.

---

### 🟡 TS-12 — manager order decides whether the moderation queue can see anything

§6 says "moderation queries deliberately bypass `visible_to()`" and §8.2 gives every soft-deleted
model `objects = ActiveManager()` plus `all_objects`. But Django admin's `ModelAdmin.get_queryset`
uses `_default_manager`, which is **the first manager declared on the class**. If `objects` is
declared first on `Post` / `Comment`, the admin changelists hide soft-deleted rows by default —
which is exactly the blindness §6 warns against.

Two ways to fix it and I'm happy with either: declare `all_objects` first, or set
`Meta.base_manager_name`. I'll also override `get_queryset` on my own admins as a belt-and-braces
measure. Flagging it because it's a one-line decision in the Architect's file that determines
whether my queue works.

*(Checked and fine: `report.post` / `report.comment` resolve even when soft-deleted, because
Django uses `_base_manager` for forward-FK descriptor access. No `RelatedObjectDoesNotExist` on
the queue.)*

---

### ⚪ TS-13 — admin hard-delete destroys the report that justified it

`Report.post` and `Report.comment` are `CASCADE`. That never fires through the product, because
posts and comments are soft-deleted (§8) — deliberate and correct. But **Django admin offers a
hard delete by default**, so Jeni actioning a report by deleting the post from admin would
cascade away the record of the thing she just actioned.

**Mine, not the Architect's.** `SET_NULL` would break the "exactly one non-null" CheckConstraint,
so the fix belongs in my admin classes: disable hard delete on `Post` / `Comment`, action via
soft delete only. TS-3's snapshot is the backstop if it ever happens anyway. Listed so it's
visible.

---

## 2 · Rate limiting — no schema, one production risk

`django-ratelimit~=4.1` is in `requirements/base.txt` ✅ and `CACHES["default"]` is Redis ✅. §6's
"no table" is right — limits belong in Redis, not Postgres.

**The risk:** `render.yaml:63` already notes `REDIS_URL` is *not* guarded — unset, the app boots
and fails on the first cache read. That puts the limiter on the critical path of **every post,
DM, follow and report**, backed by an unguarded external service (Upstash). I'll verify
django-ratelimit 4.x's exact behaviour when the cache raises before writing the decorators and
guard it either way — I'm not asserting the failure mode from memory. Raising it here because
it's a "whole site 500s" risk, not a "one feature degrades" risk. **DevOps should know**; no
schema implication.

**Scope addition I want, via Jeni:** spec §4.7 names posts, DMs and follows. **Add reports.** The
conditional constraint only stops duplicate reports of the *same* target — one account can still
flood the queue with fifty different targets, and that's a moderation DoS with no current
defence. Directly connected to TS-9: an authenticated-only report endpoint keys the limit on
`user` and sidesteps the shared-proxy-IP problem entirely.

**Two rules I'll enforce on the cron endpoint** (`/internal/cron/stale-post-nudge/`, already
stubbed as a commented `include()` in `config/urls.py`):

1. `CRON_SECRET` defaults to `""` in `base.py`. A naive comparison means an empty secret matches
   an empty/missing header and **the endpoint is wide open**. It will refuse to serve when the
   secret is empty, and compare with `hmac.compare_digest`.
2. With `CELERY_TASK_ALWAYS_EAGER=True` in prod (`deployment.md` §4), the job runs **inline in
   the HTTP request** inside `cron.yml`'s 120s curl window. I'll write it chunked and idempotent
   so a timeout mid-run is safe to retry — which TS-10's state machine already supports, since
   every transition is derivable from stored state.

**I need from DevOps via Jeni:** the URL include uncommented in `config/urls.py` (Architect's
file), and confirmation that `CRON_SECRET` is set in both places before the workflow goes live.

---

## 3 · Things I checked that are fine

Recorded so nobody re-opens them.

- **The conditional unique constraint is correct.** `condition=Q(status__in=["open","reviewing"])`
  compiles to a Postgres partial unique index and behaves exactly as §9.1 intends. TS-4 hardens
  an edge; it does not contradict this.
- **The feed demotion index is exactly right.** `Index(is_stale, -published_at)` partial on
  `deleted_at IS NULL AND status='looking'` matches `ORDER BY is_stale ASC, published_at DESC`
  column for column. Stale sinks, never hides. Q4 honoured. Nothing to change.
- **"No `ModerationAction` model in v1" is the right call and I don't want one.** Django admin
  already writes a full audit row per change (`django.contrib.admin.models.LogEntry`: who, when,
  which object, what changed), browsable at `/admin/admin/logentry/`. We get the audit trail
  free — **on the condition that every moderation action goes through the admin UI, not
  `manage.py shell`.** I'll write that condition into `docs/`. TS-5 makes the *outcome*
  queryable; it doesn't reintroduce the model.
- **Three nullable FKs + a CheckConstraint is the right shape for report targets**, and it
  matches `Notification` (§5.1). The changelist needs a computed `target` column for
  `list_display` — my code, not a schema problem.
- **`CheckConstraint(recipient != actor)` tolerates `actor=NULL`** — see TS-2.
- **`reported_user` / `post` / `comment` CASCADE never fires through the product**, because
  accounts anonymise (ADR-0001) and posts/comments soft-delete (§8). Only the admin path is
  exposed (TS-13, mine).
- **`Report.details` is `TextField(1000)`** — form-enforced only, per §0. Understood; I'll
  enforce it in the form, and require `details` when `reason='other'`.

---

## 4 · One ownership conflict to settle

`data-model.md` §11 assigns **"the 30-day anonymise job" (ADR-0001) to Trust & Safety.**
`team-prompts.md` line 48 and my seat brief don't mention it — they say report, moderation queue,
rate limiting, stale-post job. ADR-0001 is an Accounts decision about Accounts data.

I'll take it if Jeni wants — it's a scheduled job and I own the scheduled-job path. But it needs
to be one seat or the other **in writing**, or it gets built twice or not at all.

> **My preference:** Accounts owns the policy and the field-clearing logic; I own the scheduling
> harness (cron endpoint, secret, idempotency) it plugs into.

---

## 5 · What I need back

| From | What |
|---|---|
| **Jeni** | TS-6 (sparks off `last_activity_at`) · TS-7 (what clears `is_stale`) · TS-8 (30/7-day numbers, one nudge) · TS-9 (sign-in to report?) · rate-limit scope: add reports? · §4 ownership |
| **Architect** | TS-1 – TS-4 before lock · TS-5 if scope allows · TS-11 (take or leave) · TS-12 (manager order) · `condition=` not `check=` on Django 5.2 |
| **Social** (via Jeni) | TS-2 — `stale_nudge` is a system row: `actor=NULL`, `post` set, exempt from both §5.2 dedup rules |
| **Posts & Feed** (via Jeni) | TS-6/TS-7 — you own the `last_activity_at` bump on edit and the "yes, still looking" control |
| **QA** (via Jeni) | TS-1 — seed must set `last_activity_at` with `published_at`, plus ~3 posts seeded `is_stale=True` |
| **DevOps** (via Jeni) | §2 — unguarded `REDIS_URL` puts the rate limiter on the critical path; cron endpoint include + `CRON_SECRET` in both places |

Once TS-6 – TS-9 are ruled on I'll write the `is_stale` state machine (TS-10) into `docs/` as the
contract QA and Posts & Feed build against. **No code from me until the migrations land.**
