# Alongside — Tech Stack

> **Alongside** — nobody builds alone.

**Written:** 30 Jul 2026 · **Companion to:** `product-spec.md`, `roadmap.md`

---

## 0. The one decision worth confirming first

**How the frontend gets built** changes half of this document.

| Option | What it means | Verdict |
|---|---|---|
| **Django templates + HTMX** ⭐ | Server renders HTML; HTMX swaps fragments for the feed, comments, sparks, notifications | **Recommended** |
| Django + DRF + React/Next | Separate JS frontend consuming a JSON API | Not recommended here |

**Why HTMX wins for this project:**

- Alongside is almost entirely *partial page updates* — infinite-scroll feed, post a comment
  without reload, spark a post, notification badge, live search results. That is exactly what
  HTMX is for.
- A React frontend roughly doubles the work and moves that work to the *frontend*, which is
  not where the depth of this project should live.
- Django templates + HTMX ships far faster, and speed matters more than novelty here.

**DRF is still in the stack** — but for a genuine reason, not as decoration: a small, documented
JSON API over posts and search (the thing a future mobile client would use). Real DRF
experience without paying the full cost of a separate frontend.

---

## 1. Core

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Django 6.x needs 3.12+; 3.12 is the stable sweet spot |
| Framework | **Django 5.2 LTS** | Supported to Apr 2028 — no forced upgrade mid-project. Every third-party package (Channels, DRF, allauth) fully supports it. Django 6.0 is current but a 16-month non-LTS window and a thinner ecosystem |
| API | **Django REST Framework** | JSON API for posts + search |
| Database | **PostgreSQL 16** | Non-negotiable — full-text search, JSONB, proper indexes. Never SQLite for this |

## 2. Search — the star feature

| Tool | Why |
|---|---|
| **`django.contrib.postgres.search`** | `SearchVector`, `SearchRank`, `SearchQuery` — built into Django, no extra service |
| **GIN index** on a stored `search_vector` column | Keeps search fast as posts grow |
| **`pg_trgm`** extension | Trigram similarity for fuzzy/typo-tolerant matching |

**Explicitly NOT Elasticsearch.** It's a whole extra service to run, host, and pay for, and
Postgres full-text search handles this scale comfortably. Knowing *why* you didn't reach for
Elasticsearch is a better engineering answer than having used it.

## 3. Background work

| Tool | Why |
|---|---|
| **Celery** | The industry standard task queue. Used for the stale-post nudge, notification fan-out, email later |
| **Celery Beat** | Scheduled jobs — the "still looking for teammates?" nudge |
| **Redis** | Broker + result backend, and the cache |

## 4. Real-time (chat, Phase 5)

| Tool | Why |
|---|---|
| **Django Channels** | WebSockets for the chatbox |
| **Redis channel layer** | Message passing between workers |
| **Daphne** or **Uvicorn** | ASGI server (Channels needs ASGI, not WSGI) |

**Start simpler.** Phase 5 begins with plain request/response messaging over HTMX polling —
it works, it ships, and it's honest. Upgrade to Channels once the rest is solid. Chat is the
one genuine mountain in this build; don't climb it first.

## 5. Frontend

| Tool | Why |
|---|---|
| **Django templates** | Server-rendered, no build step for HTML |
| **HTMX** | Partial updates: feed pagination, comments, spark, notifications, live search |
| **Alpine.js** | Small client-side bits HTMX doesn't cover — dropdowns, modals, mobile drawer |
| **Tailwind CSS** | Fast, consistent styling; industry standard |
| **django-crispy-forms** + **crispy-tailwind** | Django forms rendered in Tailwind without hand-writing markup |

## 6. Auth & accounts

| Tool | Why |
|---|---|
| **Django `contrib.auth`** + **custom user model** | Custom user model in the *first* migration — changing it later is brutal |
| **django-allauth** | Email verification, password reset, and Google sign-in without writing OAuth by hand |
| Session auth (web) | Right choice for a server-rendered app; token auth only if the API needs it |

## 7. Media

| Tool | Why |
|---|---|
| **Pillow** | Image processing/validation |
| **Cloudinary** (free tier) + **django-cloudinary-storage** | Free image hosting with transforms. Render/Fly filesystems are ephemeral — uploads must not live on the app server |

## 8. Supporting packages

| Package | Purpose |
|---|---|
| **django-environ** | Environment config, no secrets in code |
| **django-ratelimit** | Rate limiting on posts, DMs, follows |
| **django-filter** | Filter backends for list views and the API |
| **WhiteNoise** | Serve static files without a separate CDN |

**Tags and roles: custom models, not django-taggit.** Alongside has *two* tag dimensions
(topic tags and roles-needed) with different behavior. That's core domain logic — worth
owning, and simple enough to write.

## 9. Testing & quality

| Tool | Purpose |
|---|---|
| **pytest** + **pytest-django** | Test runner |
| **factory_boy** | Test object factories |
| **Faker** | Realistic fake data — also generates the demo seed content |
| **coverage.py** | Coverage reporting |
| **Ruff** | Lint + format (already used on SpendWise) |
| **pre-commit** | Runs Ruff and tests before each commit |

## 10. Dev & ops

| Tool | Purpose |
|---|---|
| **Docker** + **docker-compose** | Five services locally: web, postgres, redis, celery worker, celery beat |
| **Gunicorn** (WSGI) → **Uvicorn/Daphne** (ASGI) | App server; switches to ASGI when Channels lands |
| **GitHub Actions** | CI — run Ruff + pytest on every push |
| **Sentry** (free tier) | Error tracking in production |
| **Git + GitHub** | Version control |

## 11. Deployment — and the honest constraint

**The free-tier situation as of July 2026:**

- **Fly.io no longer has a free tier** (trial only: 2 VM hours or 7 days).
- **Render** free web services still exist (750 hrs/month) but **spin down after 15 min idle**
  (~30s cold start), and **free Postgres expires 30 days after creation**.
- **Railway** gives $5/month credit; a real Django + Postgres + Redis app runs $15–30/month.

**Recommended free-ish setup:**

| Piece | Service | Note |
|---|---|---|
| Web app | **Render** free web service | Cold starts are acceptable for a demo |
| Database | **Neon** free Postgres | Doesn't expire, unlike Render's free tier — already proven on SpendWise |
| Redis | **Upstash** free tier | Serverless Redis, generous free allowance |
| Images | **Cloudinary** free tier | |
| Errors | **Sentry** free tier | |

**The real catch: Celery workers cost money.** Render's background workers are paid — free
tiers only cover web services. Three honest workarounds:

1. Run the Celery worker **in the same container** as the web process (via `honcho` or
   `supervisord`). Slightly impure, works fine at demo scale.
2. Trigger scheduled jobs from **GitHub Actions on a cron**, hitting a secured endpoint.
   Free, reliable, and genuinely a legitimate pattern.
3. Pay ~$7/month for a proper worker if the demo needs to be pristine.

Build with real Celery locally in Docker either way — that's where the learning and the
skill live. Deployment is a hosting-economics problem, not an architecture one.

---

## 12. Deliberately not used

Knowing what you left out (and why) is worth as much as what you picked.

| Not using | Why |
|---|---|
| Elasticsearch / OpenSearch | Postgres full-text search covers this scale; an extra service to host and pay for |
| React / Next.js | Doubles the work and moves it away from the backend |
| GraphQL | REST is simpler and fits this data |
| Kubernetes | Absurd for one app |
| Microservices | One Django app, cleanly separated into Django apps, is correct here |
| pgvector / embeddings | Tag + keyword matching is enough; semantic search is a Phase 2 idea at best |
| MongoDB | The data is deeply relational — users, posts, follows, comments |

---

## 13. Django app layout (first sketch)

```
alongside/
├── config/          # settings, urls, asgi/wsgi, celery app
├── accounts/        # custom user, profile, onboarding, follow, block
├── posts/           # posts, tags, roles, sparks, comments, saves
├── discovery/       # search, filters, feed builders
├── messaging/       # conversations, messages, chat consumers
├── notifications/   # notification model, fan-out
├── moderation/      # reports, moderation queue
└── templates/       # Django templates + HTMX partials
```

Settings split into `base.py` / `dev.py` / `prod.py`.
