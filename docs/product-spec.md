# Alongside — Product Spec (v1)

> **Alongside** — nobody builds alone.

**Status:** Requirements locked · Product spec only (technical spec comes next)
**Written:** 30 Jul 2026 (Day 17) · **Build slot:** Django Project 2, Days 26–42

---

## 1. What it is

> A place where anyone with an idea can find people to build it with.

You post an idea and the roles you need. Other people discover it, comment and suggest,
follow you, and DM you to team up. If you decide to work together, you take it from there —
the platform introduces you, it doesn't manage you.

**One sentence for the resume:** a community platform for finding collaborators on project,
startup, and business ideas.

### Who v1 is for

**Students and early builders** looking for teammates to turn an idea into a real thing.

The broader vision — small businesses, solo entrepreneurs (e.g. a crochet business owner
who needs help or investment), investors — is real and stays in the roadmap, but v1 is
deliberately designed around one group so it's focused enough to actually ship and demo.

### Why this idea

The founder has this exact problem: an app idea and no team. So does a friend running a
small crochet business alone. Existing options are either startup-founder-only
(YC Cofounder Matching, CoffeeSpace, CofoundersLab), gated/curated, or just generic
forums where team-forming happens by accident.

**Differentiator:** open, community-first, and not restricted to startup founders —
anyone with an idea, including non-technical and small-business people.

---

## 2. Product principles

These are the decisions everything else follows from. Change one and the product changes.

1. **One user, two hats.** Everyone can post ideas *and* join others'. No separate
   "talent-only" account type.
2. **Open, not gated.** Anyone can follow anyone. Anyone can DM anyone (Instagram-style).
   No approval workflow, no "apply for a role" gate.
3. **Team-forming is informal.** Roles-needed is information and a filter, not a formal
   application process. People follow, comment, and DM their way into a team.
4. **Not our call.** Once two people connect, whether they work together, how they split
   things, and swapping real contact details is entirely theirs. The platform introduces;
   it does not mediate, contract, or manage.
5. **Community first.** People who *don't* want to join still add value — suggestions and
   comments on ideas are a first-class part of the product, Reddit-style.
6. **Value before the graph.** A brand-new user must see a useful feed before they follow
   anyone. Interests are captured at sign-up for exactly this reason.

---

## 3. Core user flows

### 3.1 Sign up & onboarding
All onboarding questions are **optional** and changeable later in Settings.

1. Create account
2. *What are you here for?* → post an idea / find something to join / both
3. *What's your occupation or field?* → seeds the suggested feed
4. *Pick interest topics* (suggested from their field)
5. *(Recommended)* Suggested people and tags to follow — so they leave onboarding with a
   graph already started
6. Land on **Home**, already populated

### 3.2 Post an idea
Write it freeform (Reddit-style) → add title, tags, roles needed, stage, commitment level,
location → optionally attach images → publish.

### 3.3 Discover
Browse **Feed** (everything) or **Home** (personalized) → search by keyword → filter by
tag, role needed, commitment level, or location.

### 3.4 Connect (the core loop)
Find an idea you like →
- **Spark** it, and/or
- **Comment** with a suggestion (even if you don't want to join), and/or
- **Follow** the person (optional note — e.g. which role you'd want), and/or
- **DM** them directly

→ they get a notification → you talk in the chatbox → if you decide to build together,
you swap real contact details yourselves and go.

---

## 4. v1 feature spec

### 4.1 Accounts & profile
- Sign up / log in / log out
- Onboarding (§3.1) — all optional, editable in Settings
- **Profile:** username · profile picture · bio · skills/roles you can fill ·
  work done so far · links (GitHub / portfolio)
- Edit profile; delete account

### 4.2 Posts (ideas)
- **Fields:** title · body (freeform) · tags · roles needed · optional images
- **Stage:** just an idea / already building / launched
- **Commitment level:** casual or weekend project / serious, aiming to build a company
- **Location:** city + remote-friendly flag
- **Status:** still looking / team formed / closed
- **Auto keyword extraction** from title + body, powering search and feed matching
- Edit and delete your own posts

### 4.3 Feed & discovery
- **Feed** — all ideas; sort by newest or most-sparked
- **Home** — personalized: interest tags + people you follow
- **Cascading fallback so the feed is never empty:**
  1. people you follow + your interest tags
  2. → not enough? top posts in your field this week
  3. → still not enough? newest posts overall
- **Search bar** — keyword search across posts *and* people
- **Filters** — tag · role needed · commitment level · location

### 4.4 Social & community
- **Follow** — one-way, instant, optional note
- **Spark** — the reaction, on posts and comments. Not a "like": sparking an idea gives it
  energy and pushes it up the feed. Counts read as "42 sparks."
- **Comments** — flat (no nested threads in v1), open to everyone
- **Save / bookmark** a post for later

### 4.5 Messaging
- **DM / chatbox** — anyone can message anyone; receiver decides whether to open or reply
- Conversation list + per-conversation thread

### 4.6 Notifications
- **In-app only in v1:** bell icon + unread count
- Triggers: new DM · new follower · new comment on your post
- _(Email digests moved to Phase 2)_

### 4.7 Trust & safety
- **Block** a user
- **Report** a user, post, or comment
- **Moderation queue** — reviewed through Django admin
- **Rate limiting** on posts, DMs, and follows (anti-spam)

### 4.8 Keeping the platform alive (anti-ghosting)
The #1 documented killer in this category is ghosting and stale posts. Three deliberate
countermeasures:
1. **Commitment level + stage** on every post — prevents expectation mismatch, which is
   the root cause of most ghosting
2. **Post status** — "team formed" and "closed" get posts out of the active feed
3. **Stale-post nudge (background job)** — a post untouched for ~30 days triggers
   "Still looking for teammates?"; no response → auto-marked inactive and demoted

---

## 5. Demo & cold-start plan

Critical for a portfolio project — an empty app behind a login wall scores zero.

1. **Seed realistic demo data** on the deployed site — ~20 believable users, 40–50 project
   ideas across several fields, comments, sparks, tags, a few "team formed" posts, varied
   dates. Must look real (not `test1`, `asdf@x.com`).
2. **Public browsing** — feed, posts, and profiles readable **without signing up**.
   Account only needed to post, follow, spark, comment, or DM.
3. **Demo account** — credentials shown on the login screen so anyone can see the
   logged-in experience in one click.
4. **Honesty** — README states the site is populated with sample data. Never present it
   as real traction.

---

## 6. Phase 2 (roadmap — talk about it, don't build it yet)

- Email digests + notification preferences + @mentions
- Nested comment threads
- **Responsiveness signal** ("usually replies within a day") computed from DM behavior —
  the sharpest anti-ghosting idea, but a real chunk of work
- Smart recommendations (beyond tag matching)
- Small-business and investor modes — the crochet-business use case
- Trending tags, read receipts, richer profiles/reputation

**Deliberately not in v1:** real-time typing indicators, video, payments, contracts or
equity tooling, team/project management features.

---

## 7. Naming (settled 30 Jul 2026)

| Decision | Value |
|---|---|
| **Product name** | Alongside |
| **Tagline** | nobody builds alone |
| **Reaction** | Spark |

**Why Alongside:** "mates" is warm and inclusive — it fits a crochet business owner as
naturally as a developer — and "build" covers software, business, and craft alike. It's
also unique and searchable, and it says itself in one line:
*"Alongside — a platform where anyone can post an idea and find people to build it with."*

**Why the tagline:** "alongside" carries the feeling the name doesn't. Name explains,
tagline resonates. Goes at the top of the README and the landing page.

**Why Spark, not Like:** sparking an idea gives it energy rather than approval, and it
ranks the feed. "42 sparks" reads better than "42 likes."

**Checked and rejected:** TeamUp, CollabFinder, Guild (guild.co/.xyz/.host + Guilda,
which is literally cofounder matching), Sidekick (Sidekick Network is a direct
competitor), Saathi (very crowded in India), Flare (Danish startup raised €3.6M on it in
Apr 2026), Crewd (construction-tech startup), Alongside as a standalone name
(Seattle edtech, acquired May 2026 — and too generic a word to be searchable).

**Implementation note:** keep the Django project package generic (e.g. `collab_platform/`)
and put "Alongside" only in the UI, templates, and README — so a rename later is minutes,
not a refactor.

---

## 8. Competitive landscape (researched 30 Jul 2026)

| Platform | What it is | Gap it leaves |
|---|---|---|
| YC Cofounder Matching | The category leader, 100k+ matches | Startup founders only; users report weak filters and irrelevant matches |
| CoffeeSpace | Tinder/Hinge-style swiping for cofounders | Swipe-based, mobile-first, founders only |
| CofoundersLab | Long-running cofounder network | Reported low-quality profiles |
| CollabFinder | Partners for startups/side projects | Closest analogue; little community layer |
| Reddit (r/cofounder etc.) | Where this actually happens today | No structure — no roles, no filters, no profiles |

**Documented failure modes across the category** — designed against in §4.8:
ghosting and low commitment · weak filters → irrelevant matches · spam and low-quality
profiles · stale, abandoned posts.

**Confirmed by research, already in the design:** onboarding must deliver value before the
social graph exists (§2.6, §4.3); notifications are the retention engine (§4.6);
moderation is a design constraint, not a post-launch add-on (§4.7).

---

## 9. Next step

Technical spec: data model, API surface, and a phased build plan marking what Jeni writes
herself versus what gets scaffolded.

**Build ownership:** Jeni writes this one. Claude coaches and may scaffold plumbing
(boilerplate, seed data, test skeletons) — but the core logic (feed and matching queries,
search/keyword extraction, permissions, chat) is hers, so the project holds up under
interview questioning.
