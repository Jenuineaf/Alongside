# Alongside — Deployment, Infrastructure & Runbook

> **Alongside** — nobody builds alone.

**Owner:** DevOps seat · **Written:** 30 Jul 2026 (Day 17)
**Companion to:** `tech-stack.md` (§10, §11), `roadmap.md`

This is the operational source of truth. Every infrastructure decision, and the reasoning
behind it, lives here — no teammate can see the DevOps chat, so if it isn't written here it
doesn't exist.

**Status (31 Jul, second pass): the Architect's skeleton has landed** — `manage.py`, `config/`
(settings split, `celery.py`, `wsgi.py`, `asgi.py`, `urls.py`, `/healthz/`), and all six Django
apps now exist. That unblocks the infra layer: for the first time these files could be checked
against real code instead of against a spec.

**Three boot-breaking bugs found so far, all by reading, none by running.** Two on the first
pass (§10, 31 Jul) and one on this pass — the prod image build would have failed on a
`CLOUDINARY_URL` guard the Dockerfile didn't satisfy. Fixed.

**Still deployed: nothing.** The remaining blockers are no longer engineering — they are a
GitHub remote and five external accounts, all of which only Jeni can create. §7.0 is her
checklist. §11 is the honest status.

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
| `pyproject.toml` `[tool.ruff]` | Lint + format config — DevOps's section of a shared file (pytest and coverage are QA's) |

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
docker compose exec postgres psql -U alongside -d alongside
docker compose build --no-cache web                  # after changing requirements
```

### Known local gotchas

- **OneDrive.** The repo lives under OneDrive, so the bind mount crosses a syncing folder.
  Expect slower file watching than a plain local path. If hot reload gets unreliable, moving
  the repo to `C:\dev\alongside` fixes it — flagged, not urgent.
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

**Confirmed 31 Jul against the real code:** `base.py` reads `CELERY_TASK_ALWAYS_EAGER` from the
environment (default `False`) and sets `CELERY_TASK_EAGER_PROPAGATES = True`, so an eager task
that raises surfaces the exception instead of swallowing it — exactly what you want if tasks
are running inline in a request. `CRON_SECRET` is read into settings, and `config/urls.py`
already carries the commented-out `include()` for the cron endpoint. Both options 1 and 2
remain switchable; nothing has been foreclosed.

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

### 7.0 Accounts and credentials — Jeni's checklist

**Only Jeni can do this part.** Every account below is free, and none needs a card except
where noted. Do them in this order — later steps need values from earlier ones.

Keep a scratch note open. You are collecting **nine values**. Paste each one into the note as
you get it, because most of these pages show a secret exactly once.

> **Never paste any of these into a chat, a commit, or a file in the repo.** They go into two
> places only: Render's dashboard and GitHub's Secrets page. Both are write-only surfaces —
> you can overwrite a value but never read it back, which is the point.

---

**Step 1 — GitHub (repo + remote).** ~5 min.

The repo has local commits but no remote, so nothing can deploy and CI has never run.

1. github.com → **New repository** → name `alongside` → **Private** is fine (Render reads
   private repos on the free plan) → **do not** add a README, `.gitignore`, or licence; the
   repo already has them.
2. Copy the HTTPS remote URL it shows you.
3. From the repo root:

```bash
git remote add origin https://github.com/<your-username>/alongside.git
```

Don't push yet — §7.1 covers the first push, because the first push is what makes CI run.

*Values collected: none. Note the repo URL.*

---

**Step 2 — Neon (Postgres).** ~5 min. → `DATABASE_URL`

1. neon.tech → sign up with GitHub.
2. **New Project** → name `alongside` → Postgres **16** → region **Singapore
   (ap-southeast-1)**. Region matters: every query crosses this link, and picking a US region
   adds ~200ms to every page load.
3. On the connection panel, switch the toggle to **Pooled connection** and copy the string.
   It looks like:

   `postgresql://<user>:<password>@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`

4. **Check two things before you save it:** the hostname contains `-pooler`, and the string
   ends with `?sslmode=require`. A non-pooled URL will exhaust Neon's connection limit; a
   missing `sslmode` will fail to connect.

> ① **`DATABASE_URL`** = that string.
> **Required.** The app refuses to boot without it.

---

**Step 3 — Upstash (Redis).** ~5 min. → `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`

1. upstash.com → sign up with GitHub → **Create Database** → Redis.
2. Name `alongside` → **Regional** → region **Singapore (ap-southeast-1)** → TLS **enabled**.
3. On the database page, find the connection string in `rediss://` form (Upstash shows it
   under "Redis" / "Endpoint" — there is a copy button).

   `rediss://default:<password>@<name>.upstash.io:6379`

4. **It must start with `rediss://` — two s's.** Upstash is TLS-only; a `redis://` URL fails
   to connect with a confusing timeout rather than a clear TLS error.

> ② **`REDIS_URL`** = that string.
> ③ **`CELERY_BROKER_URL`** = **the same string**.
> ④ **`CELERY_RESULT_BACKEND`** = the same string with `/1` on the end.
>
> Upstash's free tier gives one logical database, so `/1` may be rejected. If Render logs
> show a "SELECT is not allowed" or "DB index" error, set this to the same value as ② and
> tell me — it's a one-line change, not a problem.

---

**Step 4 — Cloudinary (images).** ~5 min. → `CLOUDINARY_URL`

1. cloudinary.com → sign up for the free plan.
2. Dashboard → **API Keys** (or "Account Details") → find the **API environment variable**.
   It is already in exactly the format we need:

   `cloudinary://<api_key>:<api_secret>@<cloud_name>`

3. Copy the whole thing including the `cloudinary://` prefix.

> ⑤ **`CLOUDINARY_URL`** = that string.
> **Required.** The app deliberately refuses to boot without it — Render's disk is wiped on
> every deploy, so an app that silently saved uploads locally would lose every image with no
> error. Better to fail loudly at startup.

---

**Step 5 — Sentry (errors).** ~5 min. → `SENTRY_DSN`

1. sentry.io → sign up → **Developer** plan (free).
2. **Create Project** → platform **Django** → name `alongside`.
3. It shows you a setup snippet. You only need the **DSN** — the
   `https://<key>@o<org>.ingest.sentry.io/<project>` URL.

> ⑥ **`SENTRY_DSN`** = that URL.
> Optional. Leave it blank and Sentry simply stays off; nothing breaks.

---

**Step 6 — generate the cron secret yourself.** ~1 min. → `CRON_SECRET`

This one isn't from a service — you make it up. Run:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> ⑦ **`CRON_SECRET`** = the output.
> The **same value** goes in two places (Render **and** GitHub). If they don't match, the
> nightly job gets a 403 and silently does nothing.

---

**Step 7 — Render (the web service).** ~10 min, plus a failed first deploy that is expected.

Do this **after** pushing to GitHub (§7.1), because Render needs a repo to read.

1. render.com → sign up with GitHub → authorise access to the `alongside` repo.
2. **New → Blueprint** → select the repo. Render finds `render.yaml` and prompts for every
   value marked `sync: false`.
3. Paste ① through ⑦. Leave the email and Google fields blank for now (see below).
4. Deploy. **It will fail**, and that is expected — `ALLOWED_HOSTS` can't be filled in yet
   because Render assigns the hostname only after the service is created.
5. Once the hostname appears (`alongside-xxxx.onrender.com`), **write it down**, then set:

   > ⑧ **`ALLOWED_HOSTS`** = `alongside-xxxx.onrender.com` — hostname only, **no** `https://`
   > ⑨ **`CSRF_TRUSTED_ORIGINS`** = `https://alongside-xxxx.onrender.com` — scheme **required**

   The asymmetry is Django's, not ours, and getting it backwards is the single most common
   first-deploy mistake. Save, then **Manual Deploy → Deploy latest commit**.

**Leave blank on purpose:** `DEFAULT_FROM_EMAIL`, `EMAIL_BACKEND`, `EMAIL_HOST`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Real
email and Google sign-in belong to the Accounts seat's phase, not to getting a URL live. Every
one of them degrades gracefully when unset — email prints to the log, the Google button hides.

---

**Step 8 — GitHub repository secrets.** ~3 min.

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret name | Value |
|---|---|
| `RENDER_URL` | `https://alongside-xxxx.onrender.com` — **with** scheme, **no** trailing slash |
| `CRON_SECRET` | ⑦, character-for-character identical to Render's |

The trailing slash matters: `cron.yml` appends `/internal/cron/stale-post-nudge/`, so a
trailing slash produces a double slash and a 404.

---

### The full value → variable map

| # | Value | From | Env var | Where it goes | Required? |
|---|---|---|---|---|---|
| ① | Pooled connection string | Neon | `DATABASE_URL` | Render | **Yes — won't boot** |
| ② | `rediss://` URL | Upstash | `REDIS_URL` | Render | Boots, then fails on first cache read |
| ③ | same as ② | Upstash | `CELERY_BROKER_URL` | Render | Recommended |
| ④ | ② with `/1` | Upstash | `CELERY_RESULT_BACKEND` | Render | Recommended |
| ⑤ | API environment variable | Cloudinary | `CLOUDINARY_URL` | Render | **Yes — won't boot** |
| ⑥ | DSN | Sentry | `SENTRY_DSN` | Render | No — silently disabled |
| ⑦ | self-generated | you | `CRON_SECRET` | Render **and** GitHub | Only for scheduled jobs |
| ⑧ | Render hostname | Render | `ALLOWED_HOSTS` | Render | **Yes — won't boot** |
| ⑨ | `https://` + hostname | Render | `CSRF_TRUSTED_ORIGINS` | Render | Yes for any form/login |
| — | `https://` + hostname | Render | `RENDER_URL` | GitHub secret | Only for scheduled jobs |

`SECRET_KEY` is **not** on this list on purpose — `render.yaml` has `generateValue: true`, so
Render mints a strong one, keeps it stable across deploys, and no human ever sees it.

---

### 7.1 First deploy (one time)

1. §7.0 steps 1–6 — accounts created, values collected, remote added.
2. Push, which is also the first CI run:

```bash
git push -u origin main
```

3. **Watch the Actions tab before touching Render.** Three jobs run: Ruff, pytest, and a
   production Docker build. The Docker build is the one that matters here — it is the same
   image Render will build, so if it goes green, Render's build will too. Fixing a red build
   here costs 90 seconds; finding it on Render costs five minutes per attempt.
4. §7.0 step 7 — Render Blueprint, paste the values, expect the `ALLOWED_HOSTS` failure, set
   ⑧ and ⑨, redeploy.
5. §7.0 step 8 — GitHub secrets.
6. Verify:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://alongside-xxxx.onrender.com/healthz/
```

   `200` means the container booted, migrations ran, and gunicorn is serving. The first
   request after an idle period takes ~30s — that's the cold start, not a failure.
7. Smoke-test the admin at `/admin/`. There's no superuser yet; see §7 "Running migrations in
   production" for how to create one from your laptop.
8. Record the hostname in this doc, and tell the team the URL exists.

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
ALLOWED_HOSTS="alongside-xxxx.onrender.com" \
python manage.py migrate
```

Same shape for `showmigrations`, `createsuperuser`, or a `shell`. **Never point a local
`runserver` at the production database.**

### Production checks

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://alongside-xxxx.onrender.com/healthz/
python manage.py check --deploy      # with prod settings — flags missing security settings
```

---

## 8. Interface with the Architect's `config/` — verified 31 Jul

The skeleton has landed. This section was a list of requests; it is now a list of *checks*,
because every one of these is a place where infra and settings can silently drift apart.

### Delivered and confirmed

| Ops requirement | Status |
|---|---|
| `django-environ` reading every `.env.example` key | ✅ `base.py` |
| WhiteNoise middleware immediately after `SecurityMiddleware` | ✅ correct position — it serves nothing if placed lower |
| `STATIC_ROOT` + `CompressedManifestStaticFilesStorage` | ✅ |
| Celery read from `CELERY_BROKER_URL` / `_RESULT_BACKEND` / `_TASK_ALWAYS_EAGER` | ✅ |
| `config/celery.py`, standard shape, namespaced config | ✅ |
| `SECURE_PROXY_SSL_HEADER` for Render's proxy | ✅ — without it every redirect loops |
| `SECURE_SSL_REDIRECT`, secure cookies, HSTS, nosniff, `X_FRAME_OPTIONS` | ✅ |
| Sentry initialised only when `SENTRY_DSN` is set, `send_default_pii=False` | ✅ |
| `/healthz/` returning 200 without touching the database | ✅ `config/views.py` |
| Static storage is WhiteNoise, never Cloudinary | ✅ |
| `CONN_MAX_AGE` for Neon | ✅ 60s — a nice catch that wasn't asked for |

### The guard contract — the thing that breaks builds

`prod.py` refuses to boot on bad config, which is right. But **the `prod` Docker stage runs
`collectstatic` under `prod.py`**, so every guard also runs at image build time, with no
network and no real credentials. Any variable `prod.py` requires without a default must
therefore also appear in the Dockerfile's `collectstatic` env block.

As of 31 Jul the guards are:

| Guard in `prod.py` | Satisfied at build time by |
|---|---|
| `SECRET_KEY` ≥ 50 chars, no `replace-me`, no `dev-` prefix | 60-char throwaway key in the Dockerfile |
| `ALLOWED_HOSTS` non-empty | `ALLOWED_HOSTS="localhost"` |
| `CLOUDINARY_URL` non-empty | dummy `cloudinary://…@build` |
| `DATABASE_URL` (from `base.py`, no default) | dummy Postgres URL — never connected to |

**This is where the third bug lived.** The original spec said the key guard banned the words
`dev`/`placeholder`/`changeme`/`insecure`; the implemented guard is length + `replace-me` +
`dev-` prefix, and it added an unspecified `CLOUDINARY_URL` guard. The Dockerfile satisfied
the guard that was *specified* and not the one that was *written* — so `docker build` would
have died on `ImproperlyConfigured: CLOUDINARY_URL must be set in production`, failing CI's
Docker job and every Render deploy, with a traceback that reads like a secrets problem rather
than a build problem. Fixed in the Dockerfile, and the guard list is now pinned in the table
above.

> **Architect — standing request:** if you add or change a fail-fast guard in `prod.py`, say
> so via Jeni in the same commit. It is a Dockerfile change every time. I'd rather have the
> guards than not — they're the right design — but they're load-bearing for the image build.

### Still outstanding

- **A `/internal/cron/stale-post-nudge/` endpoint** *(needed only if Jeni approves §4
  Option 2)*. `config/urls.py` already has the `include()` line written and commented out,
  pointing at `moderation.cron_urls` — good. The view itself: POST only, compare the
  `X-Cron-Key` header against `CRON_SECRET` with `secrets.compare_digest` (not `==` — timing
  attack), 403 otherwise, then call the same task function Celery Beat would have. Trust &
  Safety owns the nudge logic; this is just the doorway.
- **`pg_trgm`.** Still nothing creates it. `django.contrib.postgres` is installed and
  tech-stack §2 requires trigram matching, but no migration runs `TrigramExtension`. Until one
  does, fuzzy search will work nowhere — not locally, not in CI, not on Neon. It must be a
  migration, not a hand-run `CREATE EXTENSION`, so all three environments match. Neon supports
  it. Architect's call, second time of asking.
- **`tests/` does not exist**, but `pyproject.toml` sets `testpaths = ["tests"]`. pytest exits
  with an error, not "no tests collected" — so **CI goes red on the very first push** for a
  reason that has nothing to do with anyone's code. QA seat: an empty `tests/` with one smoke
  test fixes it. Flagging because it will look like a CI problem and it isn't.

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
| 31 Jul (2nd pass) | `CLOUDINARY_URL` added to the `collectstatic` build env | `prod.py` as *written* guards `CLOUDINARY_URL`; the spec never asked for it. The prod image build — and therefore CI's Docker job and every Render deploy — would have failed. The full guard list is now pinned in §8 |
| 31 Jul (2nd pass) | Compose invokes `bash /app/scripts/start-dev.sh` rather than the script directly | The bind mount replaces `/app`, which masks the Dockerfile's `chmod +x`. In dev the exec bit came from however Docker Desktop maps a Windows/OneDrive path — an untested assumption on the very first run. Calling the interpreter removes the dependency |
| 31 Jul (2nd pass) | `render.yaml` marks which variables are boot-blocking | Three of them refuse to boot when unset and `REDIS_URL` fails *later* instead. Jeni fills these in by hand once; the comments are the only place that distinction is visible at fill-in time |
| 31 Jul (2nd pass) | Tailwind stays on the Play CDN through Phase 0–1 | No build step is the right call while there's no UI to build. It becomes a compiled stylesheet before the portfolio deploy — CDN Tailwind prints a console warning in production and costs a render-blocking round trip on the mid-range Android phones we target. Tracked in §11, not forgotten |

---

## 11. Blocked / not done — the honest list

**Blocked on the Architect — mostly cleared.**

The skeleton landed and §8's checklist is almost entirely green. Two things remain, neither
blocking the first deploy: the `pg_trgm` migration and the cron endpoint (§8, "Still
outstanding").

**Blocked on QA:**

- `pyproject.toml` sets `testpaths = ["tests"]` and `tests/` doesn't exist, so **CI's pytest
  job fails on the first push**. Not a code problem and not a CI problem — just a directory
  that needs to exist with something in it.

**Blocked on Jeni — this is now the critical path:**

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

- **No GitHub remote.** `git init` has run and there are local commits; the repo still needs
  creating on GitHub and pushing. Doable through the web UI without `gh`. **§7.0 step 1.**
- **Accounts to create:** GitHub repo, Neon, Upstash, Cloudinary, Sentry, Render.
  **§7.0 is the ordered checklist, with every value mapped to its env var.** About 35 minutes
  of clicking, all free, no card required.

**The deploy is otherwise ready to fire.** Nothing in the pipeline is waiting on engineering:
push → CI proves the image builds → Blueprint → paste nine values → live URL. The standing
rule is deploy early, and the only thing between here and an empty app on a real URL is §7.0.

**Still true: nothing here has ever been executed.** Every infra file is reviewed-but-unrun.
Three bugs so far (§2 exec bit, §8 `SECRET_KEY`, §8 `CLOUDINARY_URL`), all found by *reading*,
all of which would have broken the very first run. That is a fair warning about how much more
a real `docker compose up` will surface — and the reason §7.1 says watch CI's Docker build
before touching Render.

**Known soft spots to fix once things run:**

- Dependency versions are compatible-release pins chosen from tech-stack.md, **not verified
  to resolve together**. First CI run is the test. Freeze to exact pins after that.
- `build-essential` and `libpq-dev` are in the image defensively. If every dependency turns
  out to have a slim wheel, dropping them cuts image size substantially.
- No staging environment. Free tier, one service — `main` is production. Acceptable at this
  scale, but it means CI is the only safety net, which is why the Docker build runs there.
- **Tailwind is on the Play CDN** (`templates/base.html`), which compiles in the browser. Right
  call for Phase 0–1 — no build step, nothing to configure, the Designer edits a palette file
  and reloads. It has to become a compiled stylesheet before the portfolio deploy: the CDN
  prints a console warning in production and adds a render-blocking round trip on exactly the
  mid-range Android phones CLAUDE.md rule 6 targets. When that happens the Node build joins the
  Dockerfile as a stage; `.gitignore` already reserves `/static/css/tailwind.output.css`. Not
  urgent, not forgotten.
- **HTMX and Alpine are also CDN-loaded**, pinned to exact versions (`htmx.org@2.0.4`,
  `alpinejs@3.14.8`) — pinned is the important part. Same migration path as Tailwind, same
  non-urgency.
