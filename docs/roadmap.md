# Alongside — Workflow & Build Roadmap

> **Alongside** — nobody builds alone.

**Companion to:** `product-spec.md` (requirements — read that first)
**Written:** 30 Jul 2026 (Day 17) · **Build slot:** Days 26–42 (8–24 Aug 2026)

---

## Part 1 — App workflow

### 1.1 The main journey

```
Browse publicly  →  Sign up  →  Onboarding (field + interests)
                                        ↓
                          ┌─────────────┴─────────────┐
                        Home                        Feed
              (interests + follows)          (all ideas, filtered)
                          └─────────────┬─────────────┘
                          ┌─────────────┴─────────────┐
                   Post your idea                Find an idea
             (title, tags, roles needed)   (search, filter by role)
                          └─────────────┬─────────────┘
                                        ↓
                          Engage: spark · comment · follow · DM
                                        ↓
                        They get notified  →  Chatbox
                                                  ↓
                                    Team formed → swap contacts, go build
```

### 1.2 Screens to build

| # | Screen | Auth needed | Notes |
|---|--------|-------------|-------|
| 1 | Landing / public feed | No | First impression; must not be a login wall |
| 2 | Sign up / log in | — | |
| 3 | Onboarding (3 steps) | Yes | Purpose · field · interests + suggested follows. All skippable |
| 4 | Home | Yes | Personalized, with cascading fallback |
| 5 | Feed | No | All ideas; sort + filter |
| 6 | Post detail | No | Body, images, comments |
| 7 | Create / edit post | Yes | |
| 8 | Profile (own + others') | No (read) | |
| 9 | Search results | No | Posts **and** people |
| 10 | Messages (conversation list) | Yes | |
| 11 | Chat thread | Yes | |
| 12 | Notifications | Yes | Bell + unread count |
| 13 | Saved posts | Yes | |
| 14 | Settings | Yes | Edit onboarding answers, block list, delete account |

### 1.3 The three loops that matter

**Poster loop:** post an idea → get sparks, comments, follows, DMs → notified → reply →
mark "team formed" when done.

**Joiner loop:** browse or search → filter by the role you can fill → open an idea →
comment or follow or DM → chat → join.

**Return loop:** notification (in-app now, email digest in Phase 2) brings people back.
Without this the platform is a ghost town — it's what turns a one-time visit into a habit.

---

## Part 2 — Build roadmap

### Ground rules (learned the hard way on SpendWise)

1. **Deploy on day one, not at the end.** SpendWise sat undeployed until Day 17. Get an
   empty Django app live on Render during Phase 0, then every phase ships to a real URL.
2. **Custom user model in the very first migration.** In Django, swapping `AUTH_USER_MODEL`
   later is brutal. Do it before anything else exists.
3. **Every phase ends demoable.** No phase leaves the app broken.
4. **Jeni writes the logic.** Plumbing may be scaffolded (boilerplate, fixtures, test
   skeletons); the brains — feed/matching queries, search + keyword extraction,
   permissions, chat — are hers, so the project holds up in interviews.

### The phases

| Phase | Days | What ships | Demoable result |
|---|---|---|---|
| **0 — Foundation** | 26 | Django + DRF project, Postgres, Docker, git repo, **custom user model**, deployed to Render | Live URL showing "hello" |
| **1 — Accounts** | 27–28 | Signup / login / logout, profile model + CRUD, settings, delete account | Create an account, fill a profile |
| **2 — Posts & feed** | 29–31 | Post model (title, body, tags, roles needed, stage, commitment, location, status), images, create/edit/delete, Feed with sort, post detail, **public read access** | **A real, usable product** |
| **3 — Discovery** ⭐ | 32–34 | Onboarding, keyword extraction, Postgres full-text search, filters, Home feed with cascading fallback | Search + a personalized feed |
| **4 — Social** | 35–36 | Follow (+ note), spark, comments, save/bookmark, in-app notifications | The community layer works |
| **5 — Messaging** ⚠ | 37–39 | Conversation + message models, chat UI. Start request/response; upgrade to Django Channels/WebSockets if time allows | Two users can talk |
| **6 — Trust & jobs** | 40–41 | Block, report, moderation via Django admin, rate limiting, **Celery stale-post nudge** | Background jobs + moderation |
| **7 — Ship** | 42 | Seed demo data, demo account, README, screenshots, final deploy | Portfolio-ready |

⭐ **Phase 3 is the star.** Keyword extraction, full-text search, ranking, and the
cascading feed fallback are the strongest backend stories in the project. Do not rush it.

⚠ **Phase 5 is the risk.** Real-time chat via WebSockets is the only genuine mountain here.
It's also a great story — but it's the first thing to downgrade if time slips.

### If you fall behind — cut in this order

1. Image uploads on posts
2. Save / bookmark
3. **Real-time chat → simple send-and-refresh messaging** (keeps the feature, kills the hard part)
4. Suggested follows during onboarding

**Never cut:** deployment, seed data, public browsing, demo account. Those are what make
it count as a portfolio piece at all.

### The floor

**Phases 0–4 plus Phase 7** is already a complete, impressive, deployed social platform —
profiles, posts, search, personalized feed, follows, comments, notifications — even with
zero messaging. If Day 40 arrives and chat isn't working, ship that and talk about
messaging as roadmap. A polished, working subset beats a broken superset every time.

---

## Part 3 — What's still open

**Settled:** name (Alongside), tagline (nobody builds alone), reaction (Spark).

**Still to write:** the technical spec — data model, API surface, and a task-level
breakdown per phase. That's the next document.
