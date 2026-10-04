# Alongside

> **nobody builds alone**

A mobile-first web app where anyone posts an idea plus the roles they need, and other people
discover it, comment, follow, and message them to team up. Built for students, early builders
and small-business owners — the people who have an idea and no one to build it with.

The platform introduces people. It does not manage them.

---

## What it does

**Post an idea.** Title, body, what stage it's at, how serious you are, and — the part that
matters — **which roles you need**. A joiner scanning the feed is looking for exactly one
thing: a role they can fill.

**Find one.** A public feed anyone can read without an account, Postgres full-text search over
ideas *and* people, and filters on role, stage, commitment and city.

**A Home feed that is never empty.** Personalised, with a three-tier cascade behind it: people
you follow and your interests → most-sparked ideas in your field this week → newest overall.
Every tier is labelled, so the fallback reads as a deliberate choice rather than a broken
recommendation engine.

**Engage.** Spark an idea (never a "like" — counts read "42 sparks"), comment on it, follow the
person, save it for later, and message them. Anyone can message anyone; the receiver decides
whether to open it.

**Anti-ghosting, by design.** Every idea carries a **stage**, a **commitment level** and a
**status**. Mismatched expectations are the documented #1 killer in this category, so a weekend
doodle and a serious startup never look alike. A post nobody has touched in 30 days gets one
nudge asking "still looking?" — and if nobody answers, it's ranked lower. Never hidden: that
would be the system overruling the author.

---

## Stack

Python 3.12 · **Django 5.2 LTS** · Django REST Framework · **PostgreSQL 16** · Redis · Celery ·
Django templates + **HTMX** + Alpine.js + **Tailwind** · Docker · pytest · Ruff

Server-rendered, progressively enhanced. Every toggle — spark, save, follow, comment — posts to
the server and gets the re-rendered control back, so the count on screen always came from the
database and two open tabs can't disagree. All of it works with JavaScript off.

**Postgres is not interchangeable here.** `SearchVectorField`, `ArrayField`, `GinIndex`,
partial indexes and `pg_trgm` are load-bearing; on SQLite they either don't exist or silently
no-op.

---

## Running it

### Docker (everything, including Redis and Celery)

```bash
cp .env.example .env     # then fill in SECRET_KEY
docker compose up
```

→ http://localhost:8000

### Locally, without Docker

Needs PostgreSQL 16+ running. Redis is optional — without it the app falls back to a local
memory cache and runs Celery tasks inline, so `runserver` works out of the box.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements/dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements/dev.txt         # macOS / Linux

cp .env.example .env     # set SECRET_KEY and DATABASE_URL
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo --yes
.venv/Scripts/python.exe manage.py runserver
```

### The demo data

```bash
python manage.py seed_demo [--users 20] [--posts 45] [--seed 20260731] [--reset] [--yes]
```

Hand-authored, not generated: ~60 real idea posts and ~20 written bios. `Faker.text()` produces
sentence salad, and a visitor who reads two fake post bodies has already decided the site isn't
real. Faker handles names, cities and dates; it does not write the ideas.

**This is a destructive command.** It refuses to run if the database holds non-demo users unless
you pass `--yes`, `--reset` only deletes rows belonging to `is_demo` users, and it never runs
automatically on deploy.

### Tests

```bash
python -m pytest            # the whole suite
python -m pytest -m "not slow"
```

---

## How it's put together

```
accounts/      identity, profiles, follow, block, account deletion
posts/         the Post itself, tags, roles, images, comments, sparks, saves
discovery/     search, keyword extraction, filters, the Home cascade  (no models)
social/        behaviour over comments and sparks                     (no models)
messaging/     conversations and direct messages
notifications/ the bell, and fan-out
moderation/    reports, the admin queue, rate limits, scheduled jobs
```

Two conventions carry most of the weight:

**Services own every write that moves a counter.** `spark_count`, `comment_count`,
`follower_count` and the rest are denormalised, because sorting a feed by a live `COUNT(*)`
join can't use an index and the feed is the most-hit query in the app. So the rule is in one
place per app rather than in every view: a counter moves only when a row was really created or
really deleted, always through an `F()` expression inside the same transaction, and every
decrement is floored at zero.

**`visible_to(user)` is the block filter, and it is not optional.** Blocking is mutual and
global — one row hides each person from the other, everywhere — which puts a filter on about a
dozen read paths. "Every seat remembers to filter" is not a design, so the filter lives on the
querysets and every list calls it. It's free for anonymous visitors and free for the large
majority of signed-in users who have blocked nobody.

### Decisions worth reading about

Full reasoning, including the alternatives that were rejected, lives in `docs/adr/`:

| | |
|---|---|
| [ADR-0001](docs/adr/0001-account-deletion-anonymise.md) | Deleting an account **anonymises** it rather than erasing it, after a 30-day grace window. Your posts and messages stay, attributed to `[deleted]` — a two-person conversation must not become a monologue because one person left. |
| [ADR-0002](docs/adr/0002-block-is-mutual-invisibility.md) | Blocking is **full mutual invisibility**, and counters stay global. A viewer-relative count would leak exactly how many comments a blocked person wrote. |
| [ADR-0003](docs/adr/0003-block-filter-strategy.md) | How that filter is actually applied, per model, without an N+1. |
| [ADR-0004](docs/adr/0004-one-tag-vocabulary.md) | **One tag vocabulary.** Roles are curated because they're filtered; topic tags are free text because they're searched. Splitting the tag table would have made the Home feed's second tier structurally incapable of returning a row — silently. |

The rest of `docs/` is the working record: `product-spec.md` (requirements),
`roadmap.md` (the 14 screens and the phase plan), `data-model.md` (the schema and why each
constraint exists), `design-system.md`, `testing.md`, `deployment.md`.

---

## Notes

**Mobile-first, meant literally.** Every screen is built at 375px and verified to have no
horizontal scroll there. Touch targets are 44px for anything that changes state.

**Public read access is non-negotiable.** The feed, individual ideas, profiles and search all
work signed out. An account is needed only to post, spark, comment, follow or message — a
login wall on an empty social product is how it stays empty.

**Accessibility isn't a pass at the end.** State lives on `aria-pressed`, never on colour
alone; every icon is paired with a word; focus is visible on everything focusable. The palette
was checked for contrast in both directions, and the warning colour was moved 24° away from the
Spark orange so a warning banner can't read as an enormous spark.
