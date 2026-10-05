"""`manage.py seed_demo` — build the demo community.

`product-spec.md` §5 calls this critical and the roadmap lists it as never-cut,
for one reason: **it is the first and possibly only thing a stranger sees.** An
empty app behind a login wall scores zero, and a *fake-looking* populated app
scores worse than empty, because it tells the visitor the whole thing is a
mock-up. The full specification is `docs/testing.md` §7; this module implements
it and cites the clause for anything non-obvious.

    python manage.py seed_demo [--users 20] [--posts 45] [--seed 20260731]
                              [--reset] [--yes] [--quiet]

**The content is not in this file.** `_seed_corpus.py` holds the hand-authored
posts, bios and comments, and that separation is deliberate (§7.1): the corpus
is content, edited for taste, and this is code, edited for correctness. Faker
generates handles, dates and jitter. It does **not** generate ideas.

Four things here are easy to get wrong and expensive to discover late, so each
is called out at its implementation site:

1. **`bulk_create` leaves `search_vector` NULL** (§7.3). It does not fire
   `post_save`, and the vector is populated by an explicit call — so anything
   written in bulk is invisible to search while every unit test of the extractor
   still passes. Search silently returning nothing on the deployed site is the
   default outcome if nobody writes this down. Hence `recompute_search_vectors()`
   at the end, unconditionally, and an assertion in
   `tests/cross/test_seed_demo.py` that no seeded row has a null vector.
2. **The toggles are toggles.** `social.services.toggle_post_spark` and
   `toggle_save` turn a spark *off* if it is already on, so calling them on a
   second run would un-spark the entire corpus. Every call site here is guarded
   by an existence check, which keeps the service's counter rules (§7 rule 5)
   and makes the seed idempotent at the same time.
3. **`touch_activity()` sets `last_activity_at` to `Now()`.** It is called by
   `add_comment`, so seeding a comment on a 60-day-old post makes that post read
   as active this second — 45 posts all equally fresh, which is the realism
   failure §7.2 is about. `_finalise_activity_dates()` recomputes the column
   from the real child rows afterwards.
4. **`city_slug` is derived in the form layer, not in `Post.save()`.** The feed's
   city filter matches on the slug, so a seed that sets only `city` produces a
   filter dropdown where every option returns nothing (§7.2 invariant 3).

`recompute_counters()` and `recompute_search_vectors()` are deliberately
module-level and importable. `data-model.md` §7 rule 4 specifies a weekly
reconciliation task and it **does not exist yet**; when it is written it should
call these rather than reimplement them, which is also what makes running the
seed exercise the reconciliation logic for free (§7.3).
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify
from faker import Faker

from accounts import services as accounts_services
from accounts.models import Profile, ProfileInterest, ProfileSkill
from moderation.models import DEMO_MODERATOR_GROUP, Report, ReportStatus
from notifications.models import Notification, NotificationKind
from posts import services as post_services
from posts.models import (
    Comment,
    CommentSpark,
    Post,
    PostSpark,
    PostStatus,
    PostTag,
    Role,
    SavedPost,
    Tag,
)
from social import services as social_services

from . import _seed_corpus as corpus

User = get_user_model()

# Seeded users get an address under our own subdomain. Not `example.com` —
# §7.6 asserts against it, and more importantly `product-spec.md` §5.1 says the
# data must not read as a throwaway. Not a real mail provider either: these are
# fictional people, and a demo that could deliver mail to a stranger's inbox
# because somebody typo'd a handle is a mistake worth designing out.
SEED_EMAIL_DOMAIN = "demo.alongside.app"

# Everyone shares one password. These accounts cannot be logged into from the
# login screen unless their credentials are published there (§7.5 names the
# three that are), so this is a convenience for local debugging, not a secret.
SEED_PASSWORD = "alongside-demo"  # noqa: S105 - fixture credential, not a secret

# §7.2 — post dates spread over ~90 days, weighted toward the last fortnight.
DATE_SPREAD_DAYS = 90
RECENT_WINDOW_DAYS = 14

# Home tier 2's window is 7 days (`discovery/feed.py` TIER_2_WINDOW). The
# guarantee aims inside it with a margin, so a seed run does not fall out of the
# window while somebody is still looking at the site.
TIER_2_TARGET_DAYS = 5
TIER_2_MIN_POSTS = 3

# §7.2 — "2-3 posts old and untouched, so the nudge job has something real to
# act on". `moderation.tasks.send_nudges` selects on
# `last_activity_at < now - 30d AND is_stale=False AND nudged_at IS NULL`, so
# the candidates are left in exactly that state rather than pre-staled.
NUDGE_CANDIDATE_AGE_DAYS = 48
NUDGE_CANDIDATES = 3
ALREADY_DEMOTED = 1


# ── The command ──────────────────────────────────────────────────────────────


class Command(BaseCommand):
    help = "Populate the database with a realistic demo community (testing.md §7)."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=20)
        parser.add_argument("--posts", type=int, default=45)
        parser.add_argument(
            "--seed",
            type=int,
            default=20260731,
            help="RNG seed. The same seed produces the same community.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo rows first. Only touches is_demo users (§7.4).",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required when the database contains non-demo users (§7.4.2).",
        )
        parser.add_argument("--quiet", action="store_true")

    def handle(self, *args, **options):
        self.quiet = options["quiet"]
        rng = _streams(options["seed"])
        # Faker is seeded too (§4.2 rule 2) so a bad-looking run reproduces from
        # the same command. It is used for timestamps and jitter only.
        Faker.seed(options["seed"])
        fake = Faker("en_IN")

        self._guard(options)

        if options["reset"]:
            removed = reset_demo_data()
            self._say(f"reset: removed {removed} rows belonging to demo users")

        with transaction.atomic():
            people = self._ensure_people(fake, options["users"])
            demo = self._ensure_demo_accounts()
            posts = self._ensure_posts(rng["dates"], people, demo, options["posts"])

            # Before sparks, because the tier-2 guarantee moves `published_at`
            # and nominates posts that must end up with a non-zero spark count.
            tier_two = self._guarantee_tier_two(rng["tier2"], demo, posts)

            self._seed_sparks(rng["sparks"], people, demo, posts, must_spark=tier_two)
            self._seed_comments(rng["comments"], people, demo, posts)
            self._seed_saves(rng["saves"], people, demo, posts)
            self._seed_follows(rng["follows"], people, demo)

            _finalise_activity_dates()

            self._seed_statuses(rng["status"], posts, protected=tier_two)
            self._seed_staleness(rng["stale"], posts, protected=tier_two)

            self._guarantee_filters(rng["filters"], posts)
            self._seed_conversations(demo, people)
            self._seed_reports(demo, people, posts)
            self._seed_demo_notifications(demo)

            # §7.3 — counters and derived columns come from the real rows, in one
            # pass at the end. Never from the seed's own arithmetic.
            recompute_counters()
            recompute_search_vectors()

        self._report(options)

    # ── Safety (§7.4) ────────────────────────────────────────────────────────

    def _guard(self, options) -> None:
        """§7.4.2 and §7.4.6. This is what stops it running over real data.

        The check is on **non-demo users**, not on row counts: a database that
        has only ever been seeded is safe to re-seed, and one with a single real
        signup is not. `--reset` is included in the same guard rather than
        getting a stricter one of its own, because the destructive step deletes
        only `is_demo` rows anyway — the dangerous case is the same case.
        """
        if options["yes"]:
            return

        real_users = User.objects.filter(is_demo=False).count()
        if real_users:
            raise CommandError(
                f"Refusing to run: {real_users} non-demo user(s) in this database. "
                "Pass --yes if you are sure this is a demo environment. "
                "(testing.md §7.4.2)"
            )

    # ── People ───────────────────────────────────────────────────────────────

    def _ensure_people(self, fake, count: int) -> dict[str, object]:
        """The ~20 content authors. Idempotent on `username` (§7.4.3).

        Every one of them gets `is_demo=True` and **none of them gets
        `is_public_demo`** — that flag is the write restriction and belongs only
        to the three accounts whose passwords are published (§7.5). v1 of
        `testing.md` keyed the write-block off `is_demo`, which would have made
        all seventeen content authors unable to own posts: an empty-looking
        site, which is the exact failure the seed exists to prevent.
        """
        people: dict[str, object] = {}

        for entry in corpus.PEOPLE[:count]:
            user, created = User.objects.get_or_create(
                username=entry["username"],
                defaults={
                    "email": f"{entry['username'].replace('_', '.')}@{SEED_EMAIL_DOMAIN}",
                    "display_name": entry["display_name"],
                    "is_demo": True,
                },
            )
            if created:
                user.set_password(SEED_PASSWORD)
                # A 90-day-old community whose every member joined today is the
                # same tell as a feed where every post says "2 minutes ago".
                user.date_joined = fake.date_time_between(
                    start_date="-400d", end_date="-20d", tzinfo=UTC
                )
                user.last_seen_at = fake.date_time_between(
                    start_date="-20d", end_date="now", tzinfo=UTC
                )
                user.save(update_fields=["password", "date_joined", "last_seen_at"])

            self._fill_profile(user, entry)
            people[entry["username"]] = user

        return people

    def _ensure_demo_accounts(self) -> dict[str, object]:
        """The three published accounts (§7.5), and the two flags.

        `is_demo` is data lineage — `--reset` may delete the row.
        `is_public_demo` is the write restriction — the password is on a public
        web page. All three carry both. They are different questions and
        `data-model.md` §1.1.1 is explicit that conflating them breaks the seed.

        `demo.mod@` is the one that needed a product decision, and it got one:
        Decision I (Jeni, 3 Oct 2026) created a `demo_moderator` Group in
        `moderation` 0002 holding exactly `view_report` and `change_report`.
        This command **joins** the group; it does not create it. `is_public_demo`
        is an application-layer check that **Django admin never consults**, so
        without the group anyone reading the login screen could open `/admin/`
        and empty the database.
        """
        accounts: dict[str, object] = {}

        for key, entry in corpus.DEMO_ACCOUNTS.items():
            user, created = User.objects.get_or_create(
                username=entry["username"],
                defaults={
                    "email": entry["email"],
                    "display_name": entry["display_name"],
                    "is_demo": True,
                    "is_public_demo": True,
                },
            )
            # Re-asserted rather than left to `defaults`, so a row that exists
            # from an older run cannot sit there missing a flag it now needs.
            changed = []
            for field, value in (
                ("email", entry["email"]),
                ("display_name", entry["display_name"]),
                ("is_demo", True),
                ("is_public_demo", True),
                ("is_staff", key == "mod"),
            ):
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed.append(field)
            if user.is_superuser:
                # Never. The password is published; a superuser flag on it is a
                # database-deletion button with the key taped to it.
                user.is_superuser = False
                changed.append("is_superuser")
            if created:
                user.set_password(SEED_PASSWORD)
                changed.append("password")
            if changed:
                user.save(update_fields=[*changed])

            self._fill_profile(user, entry)
            accounts[key] = user

        moderator = accounts["mod"]
        try:
            group = Group.objects.get(name=DEMO_MODERATOR_GROUP)
        except Group.DoesNotExist as exc:  # pragma: no cover - migration guarantees it
            raise CommandError(
                f"Group {DEMO_MODERATOR_GROUP!r} is missing. It is created by "
                "moderation 0002; run migrations before seeding."
            ) from exc
        moderator.groups.set([group])

        return accounts

    def _fill_profile(self, user, entry) -> None:
        """Update the profile the `post_save` signal already created.

        Never `Profile.objects.create()` — `data-model.md` §1.2 creates it in the
        same transaction as the user, and a second create here would either
        duplicate it or mask the signal being broken (§4.1 rule 6).

        `avatar_url` is left blank on purpose; see the note in the module header
        of `_seed_corpus.py` and the report that accompanied this command.
        `city_slug` is derived here because nothing in the model layer does it —
        `accounts/forms.py` is the only other place it happens, and the people
        search and city filter both read the slug.
        """
        profile = Profile.objects.get(user=user)

        profile.headline = entry["headline"]
        profile.bio = entry["bio"]
        profile.occupation = entry["occupation"]
        profile.city = entry["city"]
        profile.city_slug = slugify(entry["city"])[:80]
        profile.work_done = entry["work_done"]
        profile.purpose = entry["purpose"]
        profile.custom_skills = list(entry["custom_skills"])[:3]
        profile.github_url = entry.get("github_url", "")
        profile.portfolio_url = entry.get("portfolio_url", "")
        profile.website_url = entry.get("website_url", "")

        # The field tag powers Home tier 2 and must be one of the curated rows
        # from `posts` 0002 — looked up by slug so a name reworded in the corpus
        # still resolves, and so a typo fails loudly here rather than silently
        # emptying tier 2 on the deployed site.
        field_slug = slugify(entry["field"])[:40]
        try:
            profile.field_tag = Tag.objects.get(slug=field_slug, is_curated=True)
        except Tag.DoesNotExist as exc:
            raise CommandError(
                f"{user.username}: field {entry['field']!r} is not a curated tag. "
                "Curated tags come from posts/migrations/0002."
            ) from exc

        # Onboarding is informational, not a gate (§1.2) — but a profile with
        # nothing filled in and a completed timestamp is incoherent, and the
        # brand-new demo account exists precisely to show the un-onboarded state.
        profile.onboarding_completed_at = (
            None if not entry["bio"] and not entry["skills"] else timezone.now()
        )
        profile.save()

        for slug in entry["skills"]:
            role = Role.objects.filter(slug=slug).first()
            if role is None:
                raise CommandError(
                    f"{user.username}: skill {slug!r} is not a curated role slug."
                )
            ProfileSkill.objects.get_or_create(profile=profile, role=role)

        for name in entry["interests"]:
            tag = Tag.objects.filter(slug=slugify(name)[:40]).first()
            if tag is None:
                raise CommandError(
                    f"{user.username}: interest {name!r} resolves to no tag."
                )
            ProfileInterest.objects.get_or_create(profile=profile, tag=tag)

    # ── Posts ────────────────────────────────────────────────────────────────

    def _ensure_posts(self, rng, people, demo, target: int) -> list:
        """Create the selected corpus posts plus the demo account's own three.

        **Idempotent on `(author, title)`, never on `slug`** (§7.4.3). The slug
        is `slugify(title)` plus a random suffix, so the seed cannot know the
        slug of a row it has not created yet — a slug-keyed get-or-create would
        create a second copy of all 45 posts on the second run, and the
        idempotency test in §7.6 is the test that catches it.

        `all_objects`, not `objects`: a seeded post that somebody soft-deleted
        while clicking around the demo must not come back as a duplicate.
        """
        selected = _select_posts(corpus.POSTS, set(people), target)
        created: list = []

        for entry in selected:
            author = people[entry["author"]]
            created.append(self._ensure_one_post(rng, author, entry))

        for entry in corpus.DEMO_POSTS:
            created.append(self._ensure_one_post(rng, demo["demo"], entry))

        return created

    def _ensure_one_post(self, rng, author, entry):
        # The date is drawn **before** the existence check, not after. Drawing it
        # only for new posts shifts the RNG stream on the second run by however
        # many posts already existed, which desynchronises every phase after this
        # one — see `_streams()`.
        published = _pick_published(rng)

        existing = Post.all_objects.filter(author=author, title=entry["title"]).first()
        if existing is not None:
            return existing

        return post_services.create_post(
            author,
            tags=entry["tags"],
            roles=list(Role.objects.filter(slug__in=entry["roles"])),
            custom_roles=entry["custom_roles"],
            title=entry["title"],
            body=entry["body"],
            stage=entry["stage"],
            commitment=entry["commitment"],
            city=entry["city"],
            city_slug=slugify(entry["city"])[:80],
            is_remote_friendly=entry["remote"],
            # Written at creation rather than patched afterwards. `created_at` is
            # `auto_now_add` and immutable, which is exactly why `published_at`
            # exists as a separate writable ordering key (§2.3.1). Both columns
            # are set together because `post_activity_after_publication` is a
            # real CHECK constraint: `last_activity_at >= published_at`.
            published_at=published,
            last_activity_at=published,
        )

    # ── Engagement ───────────────────────────────────────────────────────────

    def _seed_sparks(self, rng, people, demo, posts, *, must_spark) -> None:
        """Heavy-tailed sparks (§7.2), as real `PostSpark` rows.

        **The shape is scaled to the user count, and it has to be.** §7.2 asks
        for "2 posts at 40-60", which `UniqueConstraint(user, post)` makes
        arithmetically impossible with 20 users — the ceiling is 19. Rather than
        silently produce 19 and look like it missed, the distribution is
        expressed as a fraction of the available voters, so `--users 20` gives a
        believable top end of ~18 and `--users 60` gives the 40-60 the document
        asks for. Flagged to Jeni with the run report.

        Guarded `toggle_post_spark` rather than a direct insert: the service owns
        the counter rule, and the guard is what stops the second run of an
        idempotent command un-sparking the whole corpus.
        """
        voters = [*people.values(), *demo.values()]
        cap = max(0, len(voters) - 1)
        if cap == 0:
            return

        targets = _spark_targets(rng, len(posts), cap)

        # §7.2 invariant 2 — at least one post with zero sparks, guaranteed
        # rather than sampled, so the zero-spark card is visible in the live demo.
        zero_index = next(
            (i for i, post in enumerate(posts) if post.pk not in must_spark), None
        )
        if zero_index is not None:
            targets[zero_index] = 0

        for index, post in enumerate(posts):
            wanted = targets[index]
            if post.pk in must_spark:
                wanted = max(wanted, 1)
            if not wanted:
                continue

            candidates = [user for user in voters if user.pk != post.author_id]
            rng.shuffle(candidates)
            for user in candidates[:wanted]:
                # Drawn before the guard — see `_streams()`.
                when = _after(rng, post.published_at)
                if PostSpark.objects.filter(user=user, post=post).exists():
                    continue
                social_services.toggle_post_spark(user, post)
                PostSpark.objects.filter(user=user, post=post).update(created_at=when)

    def _seed_comments(self, rng, people, demo, posts) -> None:
        """Comments from the corpus, dated after the post they sit on (§7.2).

        Two separate corrections happen here and both matter:

        * `Comment.created_at` is `auto_now_add`, so every comment lands "now".
          A 70-day-old post with a comment from this second is incoherent, so
          the row is backdated with `.update()` immediately after insert.
        * `add_comment` calls `post.touch_activity()`, which sets
          `last_activity_at = Now()` and clears `is_stale`. That is correct
          behaviour for a real comment and wrong for a historical one, so
          `_finalise_activity_dates()` recomputes the column from the children
          once every comment exists.

        ~15% of posts get **zero** comments (§7.2) and at least one is
        guaranteed to, because the empty comment state has to be reachable in the
        live demo rather than only in a test fixture.
        """
        commenters = [*people.values(), *demo.values()]
        if len(commenters) < 2:
            return

        for index, post in enumerate(posts):
            # Guaranteed, not sampled: the first post in the list gets none.
            if index == 0 or rng.random() < 0.15:
                continue

            bodies = corpus.TAILORED_COMMENTS.get(post.title)
            if bodies:
                bodies = list(bodies)
            else:
                wanted = rng.choices([1, 2, 3, 4], weights=[45, 30, 17, 8])[0]
                bodies = rng.sample(corpus.GENERIC_COMMENTS, wanted)

            candidates = [user for user in commenters if user.pk != post.author_id]
            rng.shuffle(candidates)

            for body, author in zip(bodies, candidates, strict=False):
                # Every draw happens before any early exit, so the stream is the
                # same on run two as on run one (`_streams()`).
                when = _after(rng, post.published_at)
                wants_spark = rng.random() < 0.35
                sparker = rng.choice(
                    [user for user in commenters if user.pk != author.pk] or [author]
                )

                comment = Comment.all_objects.filter(
                    post=post, author=author, body=body
                ).first()
                if comment is None:
                    comment = social_services.add_comment(author, post, body)
                    Comment.all_objects.filter(pk=comment.pk).update(created_at=when)

                # A few comments collect sparks of their own — comment sparks are
                # in v1 (§2.7) and a demo where that control never has a non-zero
                # number beside it reads as unimplemented.
                if (
                    wants_spark
                    and sparker.pk != author.pk
                    and not CommentSpark.objects.filter(
                        user=sparker, comment=comment
                    ).exists()
                ):
                    social_services.toggle_comment_spark(sparker, comment)

    def _seed_saves(self, rng, people, demo, posts) -> None:
        """Saves, including the demo account's five (§7.5).

        Same guarded-toggle pattern as sparks, for the same reason: `toggle_save`
        is a toggle.
        """
        savers = list(people.values())
        for user in savers:
            for post in rng.sample(posts, min(len(posts), rng.randint(0, 4))):
                if post.author_id == user.pk:
                    continue
                if SavedPost.objects.filter(user=user, post=post).exists():
                    continue
                social_services.toggle_save(user, post)

        demo_user = demo["demo"]
        others = [post for post in posts if post.author_id != demo_user.pk]
        for post in others[:5]:
            if not SavedPost.objects.filter(user=demo_user, post=post).exists():
                social_services.toggle_save(demo_user, post)

    def _seed_follows(self, rng, people, demo) -> None:
        """A lumpy follow graph (§7.2): a few well-followed users, most with 1-4.

        `accounts.services.follow` throughout — it owns both counters and the
        `new_follower` notification, and it is already `get_or_create`-based, so
        it is idempotent without a guard.

        **`demo.new@` deliberately follows nobody and is followed by nobody.**
        That account's entire purpose is the cold-start experience (§7.5), and a
        single follow edge collapses Home tier 1 back into existence and hides
        tier 2 — the star feature — from the one visitor most likely to look.
        """
        everyone = list(people.values())
        if len(everyone) < 2:
            return

        # The handful of well-followed people: first three in corpus order, so
        # the shape is stable across runs and across seeds.
        popular = everyone[:3]
        for target in popular:
            for follower in everyone:
                if follower.pk == target.pk:
                    continue
                if rng.random() < 0.55:
                    accounts_services.follow(
                        follower, target, note=rng.choice(corpus.FOLLOW_NOTES)
                    )

        for follower in everyone:
            wanted = rng.choices([1, 2, 3, 4], weights=[30, 30, 25, 15])[0]
            for target in rng.sample(everyone, min(len(everyone), wanted + 1)):
                if target.pk == follower.pk:
                    continue
                accounts_services.follow(
                    follower, target, note=rng.choice(corpus.FOLLOW_NOTES)
                )

        # §7.5 — `demo@` follows six people, and a few follow back so the
        # account's own follower count is not zero.
        demo_user = demo["demo"]
        for target in everyone[:6]:
            accounts_services.follow(demo_user, target)
        for follower in everyone[3:8]:
            accounts_services.follow(follower, demo_user)

        # §7.2 invariant 2 — at least one user with zero followers, reachable in
        # the live demo. The last corpus person is left alone; `demo.new@` also
        # qualifies but is excluded from the graph for the reason above, and a
        # guarantee that only holds for a special-case account is a weak one.
        loner = everyone[-1]
        for follower in [*everyone, demo_user]:
            accounts_services.unfollow(follower, loner)

    # ── Status, staleness, the guarantees ────────────────────────────────────

    def _seed_statuses(self, rng, posts, *, protected) -> None:
        """~4 `team_formed`, ~2 `closed`, the rest `looking` (§7.2).

        Guaranteed rather than sampled, because "a few posts already marked team
        formed" is in the brief by name and a run that happened to produce none
        would under-sell the anti-ghosting design the product is built around.

        Through `set_status`, never a direct write: `Role.usage_count` counts
        **live posts requesting the role** (PF-6a), so moving a post out of
        `looking` has to release its roles. A `.update(status=...)` here would
        leave every role that post asked for permanently over-counted.

        `protected` holds the tier-2 guarantee's posts. Marking one of those
        `team_formed` removes it from `_base()` in `discovery/feed.py`, which
        would empty the tier the guarantee exists to fill.

        **Idempotent by target count, not by get-or-create.** A second run reads
        the remaining `looking` posts and would mark four *more* of them, so the
        demo ends up with eight team-formed posts after two runs and twelve after
        three — each individual `set_status` call perfectly correct. The §7.6
        idempotency test caught this; the guard is the fix.
        """
        wanted = {PostStatus.TEAM_FORMED: 4, PostStatus.CLOSED: 2}
        shortfall = {
            status: count - Post.all_objects.filter(status=status).count()
            for status, count in wanted.items()
        }
        if all(short <= 0 for short in shortfall.values()):
            return

        available = [
            post
            for post in posts
            if post.pk not in protected and post.status == PostStatus.LOOKING
        ]
        rng.shuffle(available)

        for status, short in shortfall.items():
            if short <= 0:
                continue
            for post in available[:short]:
                post_services.set_status(post, status)
            available = available[short:]

    def _seed_staleness(self, rng, posts, *, protected) -> None:
        """Give the stale-post nudge something real to act on (§7.2).

        Two different states, because they demonstrate two different things:

        * **Nudge candidates** — old `last_activity_at`, `is_stale=False`,
          `nudged_at=NULL`. That is exactly what `moderation.tasks.send_nudges`
          selects on, so running the job against a seeded database actually does
          something instead of returning zero.
        * **Already demoted** — `is_stale=True`. Stale posts are *ranked lower,
          never hidden* (§9 Q4), so this one is visible at the bottom of the
          feed, which is the behaviour worth being able to see.

        Posts with **the fewest comments and the oldest publication date** are
        preferred, because a post that collected five comments last week is not
        abandoned and claiming it is would make the card contradict itself. It
        is a preference rather than a filter: at `--posts 12` almost every post
        has a comment, and a guarantee that only fires at full size is not a
        guarantee — so whichever post is quietest gets aged, and its comments
        and sparks are moved back with it so the card stays coherent.

        Sparks are deliberately **not** disqualifying. `touch_activity()` is
        called by `add_comment` and not by `toggle_post_spark`, so in this
        product a spark is not activity — and a post with eleven sparks and no
        conversation is the most realistic kind of abandoned post there is.
        """
        # The two states are counted **separately**, and that is a bug fix rather
        # than tidiness. Guarding both on "posts with old activity" let the
        # 90-day date spread satisfy the guard on its own — there are always a
        # few genuinely old posts — so the function returned early and **no post
        # was ever marked `is_stale`**. The demoted-ranking behaviour (§9 Q4,
        # "ranked lower, never hidden") was therefore invisible in every run,
        # with the nudge candidates all present and nothing looking wrong.
        cutoff = timezone.now() - timedelta(days=30)
        have_candidates = Post.objects.filter(
            status=PostStatus.LOOKING,
            is_stale=False,
            nudged_at__isnull=True,
            last_activity_at__lt=cutoff,
        ).count()
        have_demoted = Post.all_objects.filter(is_stale=True).count()

        need_candidates = max(0, NUDGE_CANDIDATES - have_candidates)
        need_demoted = max(0, ALREADY_DEMOTED - have_demoted)
        if not need_candidates and not need_demoted:
            # Idempotency: a second run must not keep ageing fresh posts until
            # the whole feed looks abandoned.
            return

        candidates = [
            post
            for post in posts
            if post.pk not in protected and post.status == PostStatus.LOOKING
        ]
        # Posts with no comments first, then the oldest — so the preference is
        # honoured when the corpus subset allows it and the guarantee still holds
        # when it does not. At `--posts 12` almost every post has a comment, and
        # a guarantee that only fires at full size is not a guarantee: the stale
        # nudge is one of three named anti-ghosting countermeasures (spec §4.8),
        # so a demo where the job finds nothing is a feature nobody can see work.
        rng.shuffle(candidates)
        candidates.sort(
            key=lambda post: (
                Comment.all_objects.filter(post=post).count(),
                post.published_at,
            )
        )

        chosen = candidates[: need_candidates + need_demoted]
        for index, post in enumerate(chosen):
            age = NUDGE_CANDIDATE_AGE_DAYS + index * 6
            when = timezone.now() - timedelta(days=age)
            demoted = index >= need_candidates
            published = when - timedelta(days=4)
            Post.all_objects.filter(pk=post.pk).update(
                # `published_at` moves with it, or the CHECK constraint
                # `last_activity_at >= published_at` fails on a post published
                # after the activity we are claiming it last had.
                published_at=published,
                last_activity_at=when,
                is_stale=demoted,
                nudged_at=when + timedelta(days=31) if demoted else None,
            )
            # The children move with the parent. A post dated 48 days ago whose
            # one comment is from this morning is not abandoned, and it would
            # make the card contradict itself — which is exactly the kind of
            # detail that tells a visitor the data is generated.
            Comment.all_objects.filter(post=post).update(
                created_at=published + timedelta(days=1)
            )
            PostSpark.objects.filter(post=post).update(
                created_at=published + timedelta(days=1)
            )

    def _guarantee_tier_two(self, rng, demo, posts) -> set[int]:
        """§7.2 invariant 1 — **the single most important thing in this file.**

        > For every curated field tag assigned to a demo account, the seed
        > guarantees ≥3 posts carrying that tag, published within the last 7
        > days, with non-zero sparks.

        Sampled from a 90-day spread across ~15 tags, the expected count is well
        under one. So `demo.new@` — whose entire purpose is showing the
        cold-start experience — would fall straight through to tier 3 and the
        personalisation would be **invisible on the live site**. The cascade
        hides it perfectly: Home still looks full, and nothing errors.

        What `discovery/feed.py::_tier_2` actually requires, clause by clause,
        is why each line below exists:

            Post.objects.visible_to(user)      → not soft-deleted
                .filter(status=LOOKING)        → hence `protected` everywhere else
                .filter(tags__pk=field_tag_id) → the tag, by id, on PostTag
                .filter(published_at__gte=now-7d)
                .exclude(author=user)          → not the viewer's own posts
                .order_by("-spark_count")      → non-zero sparks, or it sorts last

        Returns the post ids the rest of the command must not break.
        """
        protected: set[int] = set()

        for key, user in demo.items():
            profile = Profile.objects.get(user=user)
            tag = profile.field_tag
            if tag is None:  # pragma: no cover - _fill_profile guarantees one
                continue

            carriers = [
                post
                for post in posts
                if post.author_id != user.pk
                and post.status == PostStatus.LOOKING
                and PostTag.objects.filter(post=post, tag=tag).exists()
            ]

            # Fallback when the selected subset does not happen to carry the tag
            # often enough — which is the normal case at `--posts 5` and should
            # never fire at `--posts 45`. The tag is added to the posts that
            # carry the fewest tags, so a post is widened rather than
            # mislabelled, and `recompute_counters()` fixes `Tag.post_count`
            # afterwards (§7.3: real rows first, counters derived).
            if len(carriers) < TIER_2_MIN_POSTS:
                spare = sorted(
                    (
                        post
                        for post in posts
                        if post.author_id != user.pk
                        and post.status == PostStatus.LOOKING
                        and post not in carriers
                    ),
                    key=lambda post: post.tags.count(),
                )
                for post in spare[: TIER_2_MIN_POSTS - len(carriers)]:
                    PostTag.objects.get_or_create(post=post, tag=tag)
                    carriers.append(post)

            for offset, post in enumerate(carriers[:TIER_2_MIN_POSTS]):
                when = timezone.now() - timedelta(
                    days=TIER_2_TARGET_DAYS - offset, hours=rng.randint(1, 20)
                )
                Post.all_objects.filter(pk=post.pk).update(
                    published_at=when, last_activity_at=when
                )
                post.published_at = when
                post.last_activity_at = when
                protected.add(post.pk)

            self._say(
                f"tier 2 for {key}: {len(carriers[:TIER_2_MIN_POSTS])} posts "
                f"carrying {tag.name!r} inside the 7-day window"
            )

        return protected

    def _guarantee_filters(self, rng, posts) -> None:
        """§7.2 invariant 3 — every filter option returns rows.

        "A filter dropdown that returns 'no results' for half its options reads
        as broken", and `discovery/feed.py::filtered_feed` filters on `stage`,
        `commitment`, `city_slug` and `roles_needed__slug` — all exact-match,
        all over `status=looking` posts only. The corpus covers every stage,
        commitment and plenty of cities, but **`_seed_statuses` runs before this
        and may have taken the last `looking` post for a value with it.**

        So this is a repair pass, not a generator: it looks for a filter value
        with no live rows and moves one post back to `looking` to cover it.
        """
        live = Q(status=PostStatus.LOOKING, deleted_at__isnull=True)

        for field, values in (
            ("stage", [entry["stage"] for entry in corpus.POSTS]),
            ("commitment", [entry["commitment"] for entry in corpus.POSTS]),
        ):
            for value in sorted(set(values)):
                if Post.all_objects.filter(live, **{field: value}).exists():
                    continue
                stranded = Post.all_objects.filter(
                    deleted_at__isnull=True, **{field: value}
                ).first()
                if stranded is not None:
                    post_services.set_status(stranded, PostStatus.LOOKING)
                    self._say(f"filters: revived a {field}={value} post")

        # ≥3 distinct city slugs with ≥2 live posts each. Reported rather than
        # repaired: the only honest fix is a bigger corpus subset, and silently
        # rewriting a post's city would make the location filter lie.
        cities = (
            Post.all_objects.filter(live)
            .exclude(city_slug="")
            .values("city_slug")
            .annotate(n=Count("pk"))
            .filter(n__gte=2)
        )
        if cities.count() < 3:
            self._warn(
                f"only {cities.count()} city slug(s) have 2+ live posts "
                "(§7.2 invariant 3 wants 3). Raise --posts."
            )

        used_roles = (
            Role.objects.filter(post_roles__post__status=PostStatus.LOOKING)
            .distinct()
            .count()
        )
        if used_roles < 5:
            self._warn(f"only {used_roles} curated role(s) in use (§7.2 wants 5+).")

    # ── Messaging, reports, notifications ────────────────────────────────────

    def _seed_conversations(self, demo, people) -> None:
        """`demo@`'s two conversations with unread messages (§7.5).

        **Written as rows rather than through a service, because there is no
        messaging service to call.** `messaging/models.py` landed with the
        Architect's `messaging` 0001, but the Builder's send path — and the
        `get_or_create_dyad` chokepoint `data-model.md` §4.1 and QA's Q-G both
        ask for — does not exist yet. So this function implements the model's
        own documented write contract by hand:

        * `dyad_key` via `messaging.models.dyad_key_for()`, which is the only
          place that key may be formatted (M11 — a string-sorted key writes
          "10:9" for one caller and "9:10" for the other, both inserts succeed,
          and you get the duplicate thread the unique constraint exists to
          prevent, starting at exactly the user ids a 20-user seed reaches);
        * `last_message_at` / `last_message_preview` denormalised from the final
          message, truncated to `PREVIEW_LENGTH` by the writer not the column;
        * the sender's own `last_read_at` current, and the **other**
          participant's `unread_count` reflecting what they have not read.

        **When the Builder lands `messaging/services.py`, replace the body of
        this function with calls to it.** Two implementations of a write
        contract is how the denormalised columns drift.
        """
        from messaging.models import (
            PREVIEW_LENGTH,
            Conversation,
            ConversationParticipant,
            Message,
            dyad_key_for,
        )

        demo_user = demo["demo"]

        for spec in corpus.DEMO_CONVERSATIONS:
            other = people.get(spec["with_user"])
            if other is None:
                continue

            origin = Post.all_objects.filter(title=spec["origin_post_title"]).first()
            conversation, _created = Conversation.objects.get_or_create(
                dyad_key=dyad_key_for(demo_user.pk, other.pk),
                defaults={"origin_post": origin},
            )
            for participant in (demo_user, other):
                ConversationParticipant.objects.get_or_create(
                    conversation=conversation, user=participant
                )

            senders = {"demo": demo_user, "other": other}
            base = timezone.now() - timedelta(days=3)
            last = None
            for index, (who, body) in enumerate(spec["messages"]):
                sender = senders[who]
                if Message.all_objects.filter(
                    conversation=conversation, sender=sender, body=body
                ).exists():
                    continue
                message = Message.objects.create(
                    conversation=conversation, sender=sender, body=body
                )
                when = base + timedelta(hours=index * 7)
                Message.all_objects.filter(pk=message.pk).update(created_at=when)
                last = (sender, body, when)

            if last is None:
                continue

            sender, body, when = last
            conversation.last_message_at = when
            conversation.last_message_preview = body[:PREVIEW_LENGTH]
            conversation.save(update_fields=["last_message_at", "last_message_preview"])

            # The sender has read their own thread; the other side has not. The
            # corpus puts the final message in the *other* person's mouth on
            # purpose, which is what makes both threads land unread in `demo@`'s
            # inbox — the §7.5 requirement. `recompute_counters()` derives
            # `unread_count` from the real rows, so nothing is set by hand here.
            ConversationParticipant.objects.filter(
                conversation=conversation, user=sender
            ).update(last_read_at=when)

    def _seed_reports(self, demo, people, posts) -> None:
        """Two open reports, so the moderation queue is not empty (§7.5).

        The reporter is a seeded content author, not `demo.mod@`: a moderator
        reviewing their own report is not a queue, it is a monologue, and the
        three conditional unique constraints key on `reporter` so a demo where
        one account files everything cannot demonstrate them.
        """
        reporters = list(people.values())
        if not reporters:
            return
        if Report.objects.filter(status=ReportStatus.OPEN).count() >= len(
            corpus.DEMO_REPORTS
        ):
            # Idempotent by count. Keying the get-or-create on the target alone is
            # not enough: `_seed_statuses` moves posts out of `looking` between
            # runs, so the "first live post" is a different row on run two and a
            # third report appears. Found by the §7.6 idempotency test.
            return

        # Ordered by slug rather than by list position, so the chosen target does
        # not move when an earlier post's status changes.
        live = list(
            Post.objects.filter(status=PostStatus.LOOKING).order_by("slug")
        )
        if not live:
            return

        for index, spec in enumerate(corpus.DEMO_REPORTS):
            reporter = reporters[index % len(reporters)]

            if spec["target"] == "comment":
                comment = (
                    Comment.objects.filter(post__in=live)
                    .exclude(author=reporter)
                    .order_by("pk")
                    .first()
                )
                if comment is None:
                    continue
                key = {"comment": comment}
            else:
                target_post = next(
                    (post for post in live if post.author_id != reporter.pk), None
                )
                if target_post is None:
                    continue
                key = {"post": target_post}

            Report.objects.get_or_create(
                reporter=reporter,
                status=ReportStatus.OPEN,
                **key,
                defaults={"reason": spec["reason"], "details": spec["details"]},
            )

    def _seed_demo_notifications(self, demo) -> None:
        """§7.5 wants `demo@` to have 4 unread notifications.

        Most of them already exist: `accounts.services.follow` and
        `social.services.add_comment` create real `new_follower` and
        `new_comment` rows as a side effect of seeding the graph, which is the
        right way round — a seeded notification that no action produced would
        link to nothing.

        The two `new_message` rows have to be created here, because there is no
        send path to produce them. `notifications` 0002's
        `notification_kind_targets` CHECK pins the shape: `new_message` requires
        `actor` and `conversation` and requires `post` and `comment` to be NULL.
        The partial unique allows exactly one *unread* row per
        (recipient, conversation), which is §5.2's rule 2 — a ten-message burst
        is one thing the user needs to know about, not ten.
        """
        from messaging.models import ConversationParticipant

        demo_user = demo["demo"]

        for participation in ConversationParticipant.objects.filter(
            user=demo_user
        ).select_related("conversation"):
            conversation = participation.conversation
            other = (
                ConversationParticipant.objects.filter(conversation=conversation)
                .exclude(user=demo_user)
                .select_related("user")
                .first()
            )
            if other is None:
                continue
            Notification.objects.get_or_create(
                recipient=demo_user,
                actor=other.user,
                kind=NotificationKind.NEW_MESSAGE,
                conversation=conversation,
                is_read=False,
                defaults={},
            )

        unread = Notification.objects.filter(recipient=demo_user, is_read=False).count()
        if unread < 4:
            self._warn(
                f"demo@ has {unread} unread notification(s); §7.5 wants 4. "
                "Seed more follows or comments on its posts."
            )

    # ── Output ───────────────────────────────────────────────────────────────

    def _report(self, options) -> None:
        """§7.4.6 — log a one-line summary of what was created."""
        counts = {
            "users": User.objects.filter(is_demo=True).count(),
            "public_demo": User.objects.filter(is_public_demo=True).count(),
            "posts": Post.objects.count(),
            "comments": Comment.objects.count(),
            "sparks": PostSpark.objects.count(),
            "saves": SavedPost.objects.count(),
            "tags": Tag.objects.count(),
            "reports_open": Report.objects.filter(status=ReportStatus.OPEN).count(),
        }
        self._say(
            "seed_demo done (seed={seed}): ".format(seed=options["seed"])
            + " ".join(f"{key}={value}" for key, value in counts.items())
        )

    def _say(self, message: str) -> None:
        if not self.quiet:
            self.stdout.write(message)

    def _warn(self, message: str) -> None:
        # Warnings are not suppressed by --quiet. A guarantee that silently did
        # not hold is the thing most worth hearing about, and --quiet exists for
        # CI noise, not for hiding failures.
        self.stderr.write(self.style.WARNING(f"seed_demo: {message}"))


# ── Selection and date shaping ───────────────────────────────────────────────


def _streams(seed: int) -> dict[str, random.Random]:
    """One independent RNG per phase, and this is a **correctness** requirement.

    One shared `Random` makes the seed non-idempotent in a way that is very hard
    to see. Randomness is consumed conditionally — `_pick_published()` is only
    called for a post that does not exist yet — so on the *second* run the
    stream is shifted by however many posts were skipped, every subsequent
    `choice` and `shuffle` returns something different, and the command cheerfully
    writes a second, different set of comments, sparks and saves on top of the
    first. Row counts climb on every run while each individual get-or-create
    looks perfectly correct.

    The §7.6 idempotency test is what caught it. Per-phase streams mean a shift
    in one phase cannot cascade into the next, and within each phase the rule is
    to **consume the randomness before the existence guard**, never after.

    Names rather than indexes so adding a phase cannot silently reuse another
    phase's stream.
    """
    return {
        name: random.Random(f"{seed}:{name}")
        for name in (
            "dates",
            "tier2",
            "sparks",
            "comments",
            "saves",
            "follows",
            "status",
            "stale",
            "filters",
        )
    }


def _select_posts(entries, usernames: set[str], target: int) -> list[dict]:
    """Pick `target` corpus posts, **preserving** the §7.2 per-author shape.

    Not `entries[:target]`: the corpus is grouped by author, so that would give
    the first eight authors everything and the last twelve nothing — a feed
    written by a third of the community, with most profiles empty.

    Not round-robin either, and that was the first implementation's mistake.
    Taking one post from every author, then a second from every author, and so
    on **flattens the distribution**: at `--posts 45` over sixteen authors every
    single one landed on exactly 2 or 3 posts. Uniform, which is the one thing
    §7.2 says the data must not be —

    > A real community is lumpy. Uniform random data feels wrong in a way people
    > notice but can't name.

    — and it is invisible in every per-post assertion, because each individual
    post is fine. Only a profile-count histogram shows it.

    So: thin **proportionally**. Each author keeps the same share of their own
    output, so whoever wrote the most still has the most at any `target`, and
    the authors the corpus gave nothing to still have nothing.

    The per-author ceiling is the corpus's, not this function's. If the shape
    wants to be steeper — §7.2 asks for two authors at 5-7 — that is a content
    edit in `_seed_corpus.py`, which is Jeni's file, not a selection change here.
    """
    by_author: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        if entry["author"] in usernames:
            by_author[entry["author"]].append(entry)

    total = sum(len(group) for group in by_author.values())
    if not total:
        return []

    ratio = min(1.0, target / total)
    # Heaviest authors first, so when rounding leaves room for one more post it
    # goes to somebody who actually wrote a lot rather than to the next author
    # alphabetically.
    order = sorted(by_author, key=lambda name: (-len(by_author[name]), name))

    selected: list[dict] = []
    for name in order:
        group = by_author[name]
        keep = max(1, round(len(group) * ratio)) if ratio > 0 else 0
        for entry in group[:keep]:
            if len(selected) >= target:
                return selected
            selected.append(entry)

    # Rounding down can leave us short of `target`; top up from what is left,
    # again heaviest-author first.
    if len(selected) < target:
        chosen = {id(entry) for entry in selected}
        for name in order:
            for entry in by_author[name]:
                if id(entry) in chosen:
                    continue
                selected.append(entry)
                if len(selected) >= target:
                    return selected

    return selected


def _pick_published(rng):
    """A ~90-day spread weighted toward the last fortnight (§7.2).

    Uniform dates over 90 days produce a feed whose first page is three weeks
    old, which reads as abandoned. Real feeds are front-loaded.
    """
    roll = rng.random()
    if roll < 0.45:
        days = rng.uniform(0.2, RECENT_WINDOW_DAYS)
    elif roll < 0.78:
        days = rng.uniform(RECENT_WINDOW_DAYS, 45)
    else:
        days = rng.uniform(45, DATE_SPREAD_DAYS)
    return timezone.now() - timedelta(days=days)


def _after(rng, moment):
    """A timestamp between `moment` and now, biased toward soon after it.

    Engagement clusters just after publication and then tails off, and nothing
    may land in the future (§7.2) — the upper bound is `now` minus a minute so
    a slow transaction cannot produce one.
    """
    ceiling = timezone.now() - timedelta(minutes=1)
    if moment >= ceiling:
        return ceiling
    span = (ceiling - moment).total_seconds()
    return moment + timedelta(seconds=span * (rng.random() ** 2.2))


def _spark_targets(rng, n_posts: int, cap: int) -> list[int]:
    """The heavy tail (§7.2), scaled to the number of available voters.

    Two posts near the ceiling, about 18% at zero, the rest in a low band. The
    fractions rather than absolute numbers are what let the same shape hold at
    `--users 3` and at `--users 60`.
    """
    targets: list[int] = []
    low = max(1, round(cap * 0.4))
    for _ in range(n_posts):
        roll = rng.random()
        if roll < 0.18:
            targets.append(0)
        elif roll < 0.82:
            targets.append(rng.randint(0, low))
        else:
            targets.append(rng.randint(low, cap))

    # Guaranteed top end, so the "most sparked" sort has something to sort.
    for index in rng.sample(range(n_posts), min(2, n_posts)):
        targets[index] = rng.randint(max(1, round(cap * 0.85)), cap)

    return targets


# ── The recompute passes (§7.3) ──────────────────────────────────────────────


def _finalise_activity_dates() -> None:
    """Recompute `last_activity_at` from the real child rows.

    `add_comment` and `toggle_*` bump activity to `Now()` — correct for a live
    comment, wrong for a backdated one, and it leaves every seeded post reading
    as active this second. So the column is derived once, at the end, from the
    newest of (`published_at`, newest comment, newest spark).

    Kept as a plain Python loop over a small table rather than a clever
    `Subquery`: it runs once per seed over tens of rows, and the
    `post_activity_after_publication` CHECK makes a subtle `Greatest()` bug here
    an `IntegrityError` at the worst possible moment.
    """
    for post in Post.all_objects.all().only("pk", "published_at"):
        newest = post.published_at
        comment = (
            Comment.all_objects.filter(post=post).order_by("-created_at").first()
        )
        if comment is not None and comment.created_at > newest:
            newest = comment.created_at
        spark = PostSpark.objects.filter(post=post).order_by("-created_at").first()
        if spark is not None and spark.created_at > newest:
            newest = spark.created_at
        Post.all_objects.filter(pk=post.pk).update(last_activity_at=newest)


def recompute_counters() -> int:
    """Recompute every denormalised counter from the rows that back it.

    `data-model.md` §7 rule 4 specifies a weekly reconciliation task and **it
    has not been written yet** — so this is both the seed's final consistency
    pass and the obvious body for that task when somebody writes it. Importing
    it from here is the point: two implementations of "what the counter should
    be" is how they come to disagree.

    Everything is scoped to `deleted_at IS NULL` where the model soft-deletes,
    because §7.1 says invisible rows do not count. `Role.usage_count` is scoped
    further, to **live posts requesting the role** (PF-6a) — not posts that
    exist, and not profiles claiming the role as a skill.

    Returns the number of rows it corrected, which is a useful number: on a
    freshly seeded database it should be small, and a large one means a service
    somewhere is not moving a counter it writes.
    """
    fixed = 0

    for post in Post.all_objects.annotate(
        real_sparks=Count("sparks", distinct=True),
        real_comments=Count(
            "comments", filter=Q(comments__deleted_at__isnull=True), distinct=True
        ),
        real_saves=Count("saves", distinct=True),
    ):
        updates = {}
        if post.spark_count != post.real_sparks:
            updates["spark_count"] = post.real_sparks
        if post.comment_count != post.real_comments:
            updates["comment_count"] = post.real_comments
        if post.save_count != post.real_saves:
            updates["save_count"] = post.real_saves
        if updates:
            Post.all_objects.filter(pk=post.pk).update(**updates)
            fixed += 1

    for comment in Comment.all_objects.annotate(
        real_sparks=Count("sparks", distinct=True)
    ):
        if comment.spark_count != comment.real_sparks:
            Comment.all_objects.filter(pk=comment.pk).update(
                spark_count=comment.real_sparks
            )
            fixed += 1

    for profile in Profile.objects.annotate(
        real_followers=Count(
            "user__follower_edges", distinct=True
        ),
        real_following=Count("user__following_edges", distinct=True),
        real_posts=Count(
            "user__posts", filter=Q(user__posts__deleted_at__isnull=True), distinct=True
        ),
    ):
        updates = {}
        if profile.follower_count != profile.real_followers:
            updates["follower_count"] = profile.real_followers
        if profile.following_count != profile.real_following:
            updates["following_count"] = profile.real_following
        if profile.post_count != profile.real_posts:
            updates["post_count"] = profile.real_posts
        if updates:
            Profile.objects.filter(pk=profile.pk).update(**updates)
            fixed += 1

    for tag in Tag.objects.annotate(
        real_posts=Count(
            "post_tags", filter=Q(post_tags__post__deleted_at__isnull=True), distinct=True
        )
    ):
        if tag.post_count != tag.real_posts:
            Tag.objects.filter(pk=tag.pk).update(post_count=tag.real_posts)
            fixed += 1

    for role in Role.objects.annotate(
        real_usage=Count(
            "post_roles",
            filter=Q(
                post_roles__post__deleted_at__isnull=True,
                post_roles__post__status=PostStatus.LOOKING,
            ),
            distinct=True,
        )
    ):
        if role.usage_count != role.real_usage:
            Role.objects.filter(pk=role.pk).update(usage_count=role.real_usage)
            fixed += 1

    fixed += _recompute_conversation_denorms()
    return fixed


def _recompute_conversation_denorms() -> int:
    """`ConversationParticipant.unread_count` from the real messages (M4/M14).

    Separate from `recompute_counters`'s body only so a database without the
    messaging tables still reconciles the rest. The column is a number not a dot
    (Decision E, Jeni 4 Oct 2026), which is exactly why it can drift and
    therefore why it belongs in the reconciliation pass.
    """
    from messaging.models import ConversationParticipant, Message

    fixed = 0
    for participant in ConversationParticipant.objects.select_related("conversation"):
        unread = Message.objects.filter(
            conversation_id=participant.conversation_id
        ).exclude(sender_id=participant.user_id)
        if participant.last_read_at is not None:
            unread = unread.filter(created_at__gt=participant.last_read_at)
        real = unread.count()
        if participant.unread_count != real:
            ConversationParticipant.objects.filter(pk=participant.pk).update(
                unread_count=real
            )
            fixed += 1
    return fixed


def recompute_search_vectors() -> int:
    """§7.3 — **the seed's most likely silent failure, closed explicitly.**

    `search_vector` is populated by an explicit `refresh_search_vector()` call,
    not by a signal (`data-model.md` §2.3: `post_save` fires before the M2M rows
    exist, so the vector would permanently contain no tags and no roles). Any row
    written by `bulk_create`, or whose tags changed after creation — which the
    tier-2 guarantee above does — therefore has a stale or null vector, and
    **search returns nothing on the deployed site while every unit test of the
    extractor passes.**

    So this runs unconditionally over every post and every profile at the end of
    every seed, and `tests/cross/test_seed_demo.py` asserts no seeded row has a
    null vector. Cheap insurance against the star feature being invisible.
    """
    from discovery.search import refresh_profile_search_vector, refresh_search_vector

    done = 0
    for post in Post.all_objects.prefetch_related("tags", "roles_needed"):
        refresh_search_vector(post)
        done += 1
    for profile in Profile.objects.select_related("user").prefetch_related(
        "skills", "interests"
    ):
        refresh_profile_search_vector(profile)
        done += 1
    return done


# ── Reset (§7.4.1, §7.4.4) ───────────────────────────────────────────────────


@transaction.atomic
def reset_demo_data() -> int:
    """Delete rows attributable to demo users, leaving the database consistent.

    **Never a `flush`, never a `TRUNCATE`** (§7.4.1). The scope is `is_demo`
    users and what cascades from them, so a real signup in the same database is
    untouched. `is_public_demo` has nothing to do with `--reset`: it is a write
    restriction, not a lineage marker.

    "**Consistent, not merely smaller**" (§7.4.4) is the part that is easy to
    miss, and there are three different orphan classes:

    1. **Stale `Tag.post_count`.** Cascading a post's deletion removes its
       `PostTag` rows and leaves the tag reading "fintech (12)" over zero posts.
       So the function finishes with `recompute_counters()` and then deletes
       non-curated tags that end at zero.
    2. **Curated tags and roles are never deleted.** `Profile.field_tag` is an
       FK and the onboarding picker depends on those rows existing *identically*
       in every environment — they come from the `posts` 0002 data migration,
       not from here.
    3. **Orphaned conversations.** Deleting a `User` cascades their
       `ConversationParticipant` row but **not** the `Conversation`, which has no
       FK to a user at all. Left alone, `--reset` accumulates a participant-less
       thread per demo conversation per run, invisible to every screen and
       counted by nothing.
    """
    from messaging.models import Conversation

    demo_user_ids = list(User.objects.filter(is_demo=True).values_list("pk", flat=True))
    if not demo_user_ids:
        return 0

    # Conversations first, and explicitly: they are the one thing the user
    # cascade does not reach.
    Conversation.objects.filter(participants__user_id__in=demo_user_ids).delete()

    # `.delete()` returns the TOTAL rows removed across every cascade, not the
    # number of users — which is the more useful number to log anyway.
    removed = User.objects.filter(pk__in=demo_user_ids).delete()[0]

    # Any conversation left with no participants at all, from an earlier run
    # that predates the line above.
    Conversation.objects.annotate(n=Count("participants")).filter(n=0).delete()

    recompute_counters()

    # Only tags nothing points at, and only user-created ones. The `PROTECT` on
    # `PostTag.tag` means a tag still in use would raise here rather than
    # silently stripping posts — correct, but a confusing way to find out, so
    # the filter is on the recomputed count.
    Tag.objects.filter(is_curated=False, post_count=0, profile_interests__isnull=True).delete()

    return removed
