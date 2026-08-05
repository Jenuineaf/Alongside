# Alongside

> **Alongside** — nobody builds alone.

A responsive, mobile-first web app where anyone posts an idea plus the roles they need, and
other people discover it, comment, follow, and DM them to team up. Users are students, early
builders, and small-business owners. The platform introduces people; it does not manage them.

**Jeni is the CEO and product owner.**

## Read before doing anything

| Doc | What's in it |
|---|---|
| `docs/product-spec.md` | Requirements — what we're building and why. Source of truth. |
| `docs/roadmap.md` | App workflow, the 14 screens, the phased build plan |
| `docs/tech-stack.md` | Every tool and why it was chosen (and what was rejected) |
| `docs/data-model.md` | The schema (written by the Architect) |

## Stack

Python 3.12 · Django 5.2 LTS · Django REST Framework · PostgreSQL 16 · Redis · Celery ·
Django Channels (later) · Django templates + HTMX + Alpine.js + Tailwind · Docker ·
pytest · Ruff

## Rules every seat follows

1. **`docs/` is the only shared memory.** Seats work in the same repo but don't share context. Any decision that affects someone else gets written into `docs/`.
2. **One owner per shared file.** The **Architect** owns every `models.py`, all migrations,
   `config/settings/`, `config/urls.py`, and base templates. Other seats request changes
   through Jeni — never edit them directly.
3. **Never invent a product decision.** If the spec doesn't answer it, ask Jeni.
4. **Stay in your area.** Work only on the files your seat owns.
5. **Nobody builds a feature before the data model is approved.**
6. **Mobile-first, always.** Must work at 375px wide with no horizontal scroll.
7. **Public read access is non-negotiable.** Feed, posts, and profiles are viewable without an
   account. Sign-in is only needed to post, follow, spark, comment, or DM.
8. **Small commits, tests as you go.** Report what changed and what other seats need to know.

## Vocabulary (get these right)

- The reaction is **Spark**, never "like." Counts read as "42 sparks."
- **Follow** is one-way and instant, with an optional note. No approval.
- **Anyone can DM anyone.** The receiver decides whether to open it. No request gate.
- A post has a **stage**, a **commitment level**, and a **status** — these are the
  anti-ghosting design, not decoration.

## Seats

Architect · Designer · DevOps · QA & Seed Data · Accounts & Profiles · Posts & Feed ·
Discovery · Social · Messaging · Trust & Safety

