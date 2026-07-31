# Buildmates — Deployment, Infrastructure & Runbook

> **Buildmates** — find people to build alongside.

**Owner:** DevOps seat · **Written:** 30 Jul 2026 (Day 17)
**Companion to:** `tech-stack.md` (§10, §11), `roadmap.md`

This is the operational source of truth. Every infrastructure decision, and the reasoning
behind it, lives here — no teammate can see the DevOps chat, so if it isn't written here it
doesn't exist.

**Status (31 Jul): infrastructure files are written and reviewed; nothing has ever been run,
and nothing is deployed.** Two boot-breaking bugs were found and fixed by review on 31 Jul —
see the decision log (§10). The whole stack is blocked on the Architect's project skeleton;
§11 has the honest list.

---

## 1. What exists right now

| File | Purpose |
|---|---|
| `Dockerfile` | Two targets — `dev` (compose) and `prod` (Render) |
| `docker-compose.yml` | The five local services |
| `.dockerignore` | Keeps secrets and noise out of image layers |
| `.env.example` | Every variable the app reads, documented |
| `requirements/{base,dev,prod}.txt` | Dependencies, each traced to a tech-stack row |
| `scripts/start-dev.sh` | Local entrypoint — migrate, then runserver |
| `scripts/start-web.sh` | Production entrypoint — migrate, then gunicorn |
| `.github/workflows/ci.yml` | Ruff + pytest + migration-drift check + Docker build |
| `.github/workflows/cron.yml` | Scheduled jobs (stands in for Celery Beat) |
| `render.yaml` | Render Blueprint for the web service |
| `.pre-commit-config.yaml` | Ruff, secret detection, large-file guard |
| `.gitignore` | `.env` first, deliberately |

**None of it has been executed.** Docker Desktop is not installed on the build machine, so
these files are reviewed-but-unverified. First `docker compose up` is the real test. Treat
§11 as the honest status, not this table.

---

## 2. Local development

### One-time setup

1. Install **Docker Desktop for Windows** (needs WSL2 — Windows 11 Home supports it).
2. From the repo root:

```bash
cp .env.example .env
```

3. Generate a real `SECRET_KEY` and paste it into `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

4. Bring the stack up:

```bash
docker compose up --build
```

App at **http://localhost:8000**. Postgres on 5432 and Redis on 6379 are published to the
host so a GUI client can reach them.

### The five services

| Service | Image / target | Role |
|---|---|---|
| `web` | `Dockerfile` target `dev` | Django dev server, hot reload via bind mount |
| `postgres` | `postgres:16-alpine` | Database, data in a named volume |
| `redis` | `redis:7-alpine` | Celery broker + result backend + cache |
| `worker` | same as `web` | `celery -A config worker` |
| `beat` | same as `web` | `celery -A config beat` — the scheduler |

`worker` and `beat` reuse the web image via a YAML anchor. One image, one dependency
install, three processes.

### Everyday commands

```bash
docker compose up                                    # start
docker compose down                                  # stop
docker compose down -v                               # stop AND wipe the database
docker compose logs -f web                           # follow one service
docker compose exec web python manage.py migrate     # migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py shell
docker compose exec web pytest                       # tests
docker compose exec web ruff check .                 # lint
docker compose exec postgres psql -U buildmates -d buildmates
docker compose build --no-cache web                  # after changing requirements
```

### Known local gotchas

- **OneDrive.** The repo lives under OneDrive, so the bind mount crosses a syncing folder.
  Expect slower file watching than a plain local path. If hot reload gets unreliable, moving
  the repo to `C:\dev\buildmates` fixes it — flagged, not urgent.
- **Line endings.** `scripts/*.sh` must stay LF. Git on Windows may rewrite them to CRLF,
  which makes the container fail with `exec format error` or `no such file or directory`.
  If that happens: `git config core.autocrlf input`, then re-checkout the scripts.
  *Checked 31 Jul: both scripts are LF and `core.autocrlf` is already `input`. Fine.*

- **The exec bit on `scripts/*.sh`.** Windows has no Unix permission bit, so git committed both
  entrypoints as mode `100644`. The container invokes them directly
  (`CMD ["/app/scripts/start-web.sh"]`, and compose's `command:`), so a non-executable script
  means **every service dies on boot with "permission denied"** — the first `docker compose up`
  and the first Render deploy would both have failed. Fixed 31 Jul two ways: the git index is
  now `100755` (`git update-index --chmod=+x`), and both Dockerfile stages `chmod +x` after
  `COPY` so a future Windows-side re-add can't silently reintroduce it. If you ever add a new
  `.sh`, run `git update-index --chmod=+x` on it and confirm with `git ls-files -s scripts/`.
- **`pg_trgm`.** Trigram search (tech-stack §2) needs the extension. It should be created by
  a Django migration (`TrigramExtension`), not by hand — that way it exists identically in
  local, CI, and Neon. **Architect's call**; noted here so it isn't missed.

---

## 3. Production topology

| Piece | Service | Plan | Why |
|---|---|---|---|
| Web | **Render** web service, Docker runtime | Free | Free tier still covers web services |
| Database | **Neon** Postgres | Free | Doesn't expire — Render's free Postgres dies after 30 days. Already proven on SpendWise |
| Redis | **Upstash** | Free | Serverless, generous allowance, TLS (`rediss://`) |
| Images | **Cloudinary** | Free | Render's filesystem is ephemeral; uploads cannot live on the app server |
| Errors | **Sentry** | Free | |
| Static files | **WhiteNoise** | — | Served by the app, no CDN needed at this scale |
| Scheduled jobs | **GitHub Actions cron** | Free | See §4 |

**Region: Singapore.** Nearest Render region to Bangalore. Neon and Upstash should be
created in the same region — a cross-region database round trip on every query would be the
single biggest avoidable latency in the app.

### Accepted trade-offs

- **Cold starts.** The free web service sleeps after 15 minutes idle; the next request waits
  ~30s. Acceptable for a portfolio demo. Mitigations if it becomes annoying are in §4.
- **One instance.** No horizontal scaling, which is *why* boot-time migrations are safe.
- **Ephemeral disk.** Nothing may be written to local disk expecting it to survive. All
  uploads go to Cloudinary.

---

## 4. The Celery problem — DECISION NEEDED FROM JENI

Render's background workers are a paid product; the free tier is web services only. So
production has no place to run `celery worker` or `celery beat`. tech-stack.md §11 lists
three workarounds. Here is the analysis and my recommendation.

### The options

**Option 1 — run worker + beat inside the web container** (honcho/supervisord)

Looks the most "correct", and works the least well. The free web service **spins down after
15 minutes of inactivity**, and everything in the container goes down with it. A beat process
inside a sleeping container does not fire. The nightly stale-post nudge — the one job we
actually schedule — would silently never run, and we'd only find out when someone asked why
no nudges went out. It also splits ~512MB of RAM three ways.

**Option 2 — GitHub Actions cron hitting a secured endpoint**

A workflow POSTs to `/internal/cron/<job>/` with a shared-secret header on a schedule. Free,
fires reliably whether or not the app is awake, and the request itself wakes the service.
Genuinely a normal pattern — plenty of production systems drive scheduled work from an
external scheduler rather than an in-cluster one.

**Option 3 — pay ~$7/month for a real Render worker**

Buys a pristine, fully faithful deployment. Costs ₹600/month for a portfolio project.

### Recommendation

**Option 2, plus `CELERY_TASK_ALWAYS_EAGER = True` in production.**

Two different needs, two different answers:

- **Scheduled work** (the stale-post nudge) → GitHub Actions cron. It's the only option that
  actually fires on a service that sleeps.
- **On-demand async work** (notification fan-out) → runs inline in the request. At demo
  scale that's a handful of database inserts; the latency cost is milliseconds, and the
  alternative is tasks queuing into Redis with nothing on the other end to consume them —
  which is worse than not having Celery at all, because it fails *silently*.

The architecture doesn't change. The task code, the decorators, the queue, the beat schedule
are all real and all exercised locally in Docker every day. What changes in production is
only the executor. That is also a better interview answer than either alternative: *"Celery
is wired properly and runs as a real worker locally. In production I ran tasks eagerly and
moved the schedule to an external cron, because the host's free tier has no always-on
process and an in-container scheduler on a service that spins down would have missed its
schedule without telling me. If it needed to scale I'd move the worker back — it's a
hosting-economics decision, not an architecture one."*

Upgrade path if the demo ever needs to be pristine: pay for a worker, flip
`CELERY_TASK_ALWAYS_EAGER` to `False`, delete the cron workflow. Roughly ten minutes of work,
no code changes.

### What this needs from Jeni

Say yes, or pick a different option. Nothing here is locked in yet — `cron.yml` is written
but inert until its secrets exist, and `render.yaml` sets the eager flag which is one line
to change.

### If cold starts become the problem

The GitHub Actions cron already wakes the app daily. If you want it warm during a specific
window (say, while a recruiter is likely to click the link), a second workflow pinging
`/healthz/` every 14 minutes keeps it up. Render's free tier allows 750 instance-hours a
month and a permanently-awake single service uses about 720, so it fits — just barely, and
only for one service. Not enabled; noted as available.

---

## 5. Environment & secrets

**Rules:**

1. Secrets never enter git. `.env` is the first line of `.gitignore`; `detect-secrets` and
   `detect-private-key` run in pre-commit.
2. Every variable the app reads is documented in `.env.example`, with a safe placeholder.
3. Production values live in Render's dashboard (`sync: false` in `render.yaml` means Render
   prompts for them and never writes them to the repo).
4. `SECRET_KEY` in production is generated by Render (`generateValue: true`) and never seen
   by a human.
5. Adding a variable means updating `.env.example`, `render.yaml`, and the CI `env:` block in
   the same commit. A variable that exists in only one of the three is a future outage.

**Where each secret lives:**

| Secret | Local | CI | Production |
|---|---|---|---|
| `SECRET_KEY` | `.env` | hardcoded CI-only value | Render `generateValue` |
| `DATABASE_URL` | `.env` → compose Postgres | GH Actions service container | Render env → Neon |
| `REDIS_URL` | `.env` → compose Redis | GH Actions service container | Render env → Upstash |
| `CRON_SECRET` | `.env` | n/a | Render env **and** GitHub repo secret — must match |
| `CLOUDINARY_URL` | blank (local files) | blank | Render env |
| `SENTRY_DSN` | blank (disabled) | blank | Render env |
| `GOOGLE_CLIENT_*` | blank (button hidden) | blank | Render env |

**Required GitHub repository secrets:** `RENDER_URL`, `CRON_SECRET`.

---

## 6. CI

`.github/workflows/ci.yml` runs on every push to every branch, and on PRs to `main`. Three
parallel jobs:

| Job | What it does |
|---|---|
| `lint` | `ruff check` + `ruff format --check` |
| `test` | Postgres 16 + Redis 7 service containers → migration-drift check → migrate → pytest with coverage |
| `docker` | Builds the `prod` image target |

Two deliberate choices:

- **`makemigrations --check --dry-run` runs before the tests.** This fails the build when a
  model changed without a migration. On SpendWise the test suite built its schema with
  `create_all` instead of running migrations, which made model/migration drift structurally
  invisible — the tests were green while production was broken. This check is that lesson,
  encoded. **Tests must run against migrated schema**, not a synthesized one. QA seat: please
  hold that line.
- **The Docker build runs in CI.** A broken Dockerfile should fail in 90 seconds on a PR, not
  after a five-minute Render deploy.

`CELERY_TASK_ALWAYS_EAGER=True` in CI, so tests never need a worker process.

---

## 7. Deploy runbook

### First deploy (one time)

1. Push the repo to GitHub (`Jenuineaf/buildmates`), branch `main`.
2. **Neon** → new project, region Singapore → copy the **pooled** connection string. It must
   end in `?sslmode=require`.
3. **Upstash** → new Redis database, region Singapore → copy the `rediss://` URL (TLS —
   two s's; a `redis://` URL will fail to connect).
4. **Cloudinary** → copy the `CLOUDINARY_URL`.
5. **Sentry** → new Django project → copy the DSN.
6. **Render** → New → Blueprint → connect the repo. Render reads `render.yaml` and prompts
   for every `sync: false` variable. Paste the values from steps 2–5.
7. First deploy fails on `ALLOWED_HOSTS` — you don't know the hostname until Render assigns
   it. Once it appears (`buildmates-xxxx.onrender.com`), set:
   - `ALLOWED_HOSTS` = `buildmates-xxxx.onrender.com`
   - `CSRF_TRUSTED_ORIGINS` = `https://buildmates-xxxx.onrender.com`

   then redeploy. This is expected, not a failure — write the hostname down.
8. GitHub → repo → Settings → Secrets → Actions → add `RENDER_URL`
   (`https://buildmates-xxxx.onrender.com`) and `CRON_SECRET` (same value as Render's).
9. Verify: `curl -sS https://buildmates-xxxx.onrender.com/healthz/` returns 200.

### Every deploy after that

Merge to `main`. Render auto-deploys; `start-web.sh` runs migrations, then gunicorn.

### Rollback

Render keeps every previous deploy.

> Render dashboard → the service → **Events** → find the last good deploy → **Rollback to
> this deploy**. Takes ~2 minutes.

**Rollback does not undo a database migration.** If the bad deploy migrated the schema,
roll the code back first (stops the bleeding), then reverse the migration deliberately:

```bash
# from a local shell, pointed at production — see "Production shell" below
python manage.py migrate <app_label> <previous_migration_name>
```

Write backwards-compatible migrations and this stays rare: add columns nullable, don't drop
a column in the same deploy that stops using it.

### Reading logs

- **Live:** Render dashboard → service → **Logs**. Streams stdout/stderr; gunicorn is
  configured to log access and errors there.
- **Errors with a stack trace and request context:** Sentry.
- **Free-tier logs are not retained long.** If something matters, Sentry is where it lives.

### Running migrations in production

Normally automatic on boot. To run one by hand, Render's free plan has no web shell, so
connect from your laptop with production credentials:

```bash
DATABASE_URL="<neon pooled url>" \
DJANGO_SETTINGS_MODULE=config.settings.prod \
SECRET_KEY="<any strong value — not used for migrations>" \
ALLOWED_HOSTS="buildmates-xxxx.onrender.com" \
python manage.py migrate
```

Same shape for `showmigrations`, `createsuperuser`, or a `shell`. **Never point a local
`runserver` at the production database.**

### Production checks

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://buildmates-xxxx.onrender.com/healthz/
python manage.py check --deploy      # with prod settings — flags missing security settings
```

---

## 8. What DevOps needs from the Architect

These land in `config/`, which the Architect owns. Requesting rather than editing.

**`config/settings/base.py`**

- `django-environ` reading every key in `.env.example`.
- `INSTALLED_APPS` — nothing ops-specific required.
- WhiteNoise: `whitenoise.middleware.WhiteNoiseMiddleware` **immediately after**
  `SecurityMiddleware` (order matters — it won't serve anything if placed lower), plus
  `STATIC_ROOT = BASE_DIR / "staticfiles"` and the compressed-manifest storage backend.
- Celery config read from `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`,
  `CELERY_TASK_ALWAYS_EAGER`.

**`config/settings/prod.py`**

- **Refuse to boot on a weak `SECRET_KEY`** — fewer than 32 characters, or containing any of
  `dev`, `placeholder`, `changeme`, `insecure`. SpendWise does this; it's cheap and it has
  caught real mistakes.

  **The Dockerfile depends on this exact list.** The `prod` stage runs `collectstatic` with
  `config.settings.prod` loaded, so it must pass a throwaway key that survives the guard. That
  key is hardcoded in the Dockerfile and deliberately contains none of the banned words. If you
  add a word to the banned list, check the Dockerfile in the same commit — otherwise the image
  build fails, and it fails at `docker build` time with a Django traceback that looks nothing
  like a secrets problem.

- **Static files storage must be WhiteNoise, never Cloudinary.** `collectstatic` runs at image
  build time with no network and no real credentials. Cloudinary is for *media* (user uploads)
  only. Pointing `STORAGES["staticfiles"]` at Cloudinary would make every image build reach out
  to an API it cannot authenticate against.

- **`CSRF_TRUSTED_ORIGINS` must have a default or tolerate being unset**, or read it in a way
  that doesn't explode when absent. The image build passes a dummy value, but any *other*
  required-with-no-default variable added to `prod.py` becomes a new build-time failure. Rule of
  thumb: if `prod.py` hard-requires a variable, it must also appear in the Dockerfile's
  `collectstatic` env block.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` — required behind Render's
  proxy, or every redirect loops.
- `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS.
- Sentry initialised only when `SENTRY_DSN` is set, with `send_default_pii=False`.

**`config/celery.py`** — DevOps owns the Celery wiring per the seat split, but the file sits
in the Architect's package. Standard shape (`app = Celery("config")`,
`config_from_object("django.conf:settings", namespace="CELERY")`, `autodiscover_tasks()`),
imported from `config/__init__.py`. Whoever creates the skeleton can drop it in; DevOps will
review and own it thereafter.

**A `/healthz/` view.** `render.yaml` and the deploy checks both point at it. Must return
200 without touching the database — a health check that queries Postgres turns a database
blip into a restart loop. Plain `HttpResponse("ok")` is right.

**A `/internal/cron/stale-post-nudge/` endpoint** *(only if Jeni approves §4 Option 2)* —
POST only, compares the `X-Cron-Key` header against `CRON_SECRET` with
`secrets.compare_digest`, 403 otherwise, then calls the same task function Celery Beat would
have called. Trust & Safety seat owns the nudge logic; this is just the doorway.

---

## 9. The ASGI switch (Phase 5, deferred)

When Django Channels lands for real-time chat, WSGI/gunicorn is no longer enough.

1. Uncomment `channels`, `channels-redis`, `uvicorn[standard]` in `requirements/prod.txt`.
2. `start-web.sh` swaps gunicorn for
   `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker`.
3. Redis channel layer points at the same Upstash URL.
4. **Verify Upstash's free tier allows enough concurrent connections** before committing —
   WebSockets hold connections open, which is a different usage profile than Celery's.

Not before Phase 5. Per roadmap, messaging starts as request/response over HTMX polling, and
that needs none of this.

---

## 10. Decision log

| Date | Decision | Why |
|---|---|---|
| 30 Jul | Neon for Postgres, not Render's | Render's free database expires after 30 days; Neon's doesn't. Proven on SpendWise |
| 30 Jul | Upstash for Redis | Render has no free Redis |
| 30 Jul | Region Singapore everywhere | Nearest to Bangalore; cross-region DB hops would dominate latency |
| 30 Jul | Migrations run on boot | Free tier is a single instance, so no migration race is possible. Revisit if we ever scale out |
| 30 Jul | Static via WhiteNoise, baked at image build | No CDN needed at this scale; baking keeps boot fast |
| 30 Jul | Docker build runs in CI | Fail on a PR in 90s rather than after a 5-minute Render deploy |
| 30 Jul | `makemigrations --check` in CI | SpendWise's tests were green against a synthesized schema while migrations were broken. Never again |
| 30 Jul | One Dockerfile, two targets | Dev and prod share dependency layers; no second file to drift |
| 30 Jul | Compatible-release pins (`~=`) | Nothing is verified yet. Freeze to exact pins once CI is green — see §11 |
| 30 Jul | **Proposed:** GH Actions cron + eager tasks in prod | §4. **Awaiting Jeni** |
| 31 Jul | Entrypoint scripts forced to mode 755 in the git index **and** `chmod +x` in both Dockerfile stages | Windows can't store the exec bit; without it every container dies on boot with "permission denied". Two independent fixes because the git-index one is easy to lose on a Windows re-add |
| 31 Jul | Build-time `SECRET_KEY` no longer contains the word "placeholder" | The prod image runs `collectstatic` under `prod.py`, whose spec'd guard rejects keys containing `placeholder` — the Dockerfile would have failed its own security check. Banned-word list is now pinned in §8 so the two can't drift |
| 31 Jul | `CSRF_TRUSTED_ORIGINS` added to the `collectstatic` build env | Any variable `prod.py` requires without a default becomes an image-build failure. §8 now states the rule |

---

## 11. Blocked / not done — the honest list

**Blocked on the Architect:**

- Everything in §8. There is no `manage.py`, no `config/`, no `requirements` consumer — so
  the Dockerfile cannot build and compose cannot start. All infra files are written against
  the layout in tech-stack.md §13 and will work the moment the skeleton lands.

**Blocked on Jeni:**

- **The §4 Celery decision.**
- **Local toolchain — audited 31 Jul, and it's thinner than previously recorded:**

  | Tool | State | Needed for |
  |---|---|---|
  | git | ✅ installed | — |
  | Python | ⚠️ **3.14.6** | Stack targets 3.12. Irrelevant inside Docker; matters only for a no-Docker fallback, where Django 5.2 on 3.14 is untested |
  | Node | ✅ installed | Tailwind build |
  | **WSL2** | ❌ **not installed** | Prerequisite for Docker Desktop |
  | **Docker Desktop** | ❌ not installed | Everything local |
  | **GitHub CLI (`gh`)** | ❌ not installed | Convenience only — the web UI works |

  The earlier note said "install Docker Desktop." That understated it: WSL2 has to be installed
  and the machine rebooted *first* (`wsl --install`, reboot, then Docker Desktop). Budget an
  hour including the reboot, not ten minutes.

- **No GitHub remote.** `git init` has run and there is one local commit; the repo still needs
  creating on GitHub and pushing. Doable through the web UI without `gh`.
- **Accounts to create:** Render, Neon, Upstash, Cloudinary, Sentry.

**Still true: nothing here has ever been executed.** Every infra file is reviewed-but-unrun.
The two bugs found on 31 Jul (§2 exec bit, §8 `SECRET_KEY`) were both found by *reading*, and
both would have broken the very first run — which is a fair warning about how much more a real
`docker compose up` will surface.

**Known soft spots to fix once things run:**

- Dependency versions are compatible-release pins chosen from tech-stack.md, **not verified
  to resolve together**. First CI run is the test. Freeze to exact pins after that.
- `build-essential` and `libpq-dev` are in the image defensively. If every dependency turns
  out to have a slim wheel, dropping them cuts image size substantially.
- No staging environment. Free tier, one service — `main` is production. Acceptable at this
  scale, but it means CI is the only safety net, which is why the Docker build runs there.
