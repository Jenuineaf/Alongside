"""The seed command's own test suite — `testing.md` §7.6, every assertion in it.

> It runs at Phase 7 (Day 42 — the last day). A seed that quietly broke in Phase
> 4 and is discovered on the final afternoon is the worst possible timing, so it
> is tested from the day it is written.

Two conventions worth knowing before adding to this file.

**It runs the real command, not a helper.** `call_command("seed_demo", ...)` with
a small `--users` / `--posts`, so what is tested is the thing that will be run
against the deployed database. A test that exercised a factory instead would
pass while the command itself was broken.

**Nothing here asserts on a hand-counted total.** The seed's whole design is
distributions and guarantees, not fixed numbers, so the assertions are shaped
the same way: "at least one post has zero comments", never "exactly nine do".
A test that pins a sampled count fails on the next seed value and gets deleted
by whoever is in a hurry — which is how a suite stops being trusted.
"""

import re
from datetime import timedelta

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count, F, Q
from django.utils import timezone

from accounts.models import Follow, Profile
from discovery.feed import TIER_2_WINDOW, home_feed
from moderation.models import DEMO_MODERATOR_GROUP, Report, ReportStatus
from posts.models import Comment, Post, PostSpark, PostStatus, Role, SavedPost, Tag

pytestmark = pytest.mark.django_db

User = get_user_model()

# Small on purpose: these run on every push, and most shapes under test are
# fractions of the corpus rather than absolute counts.
#
# **Not arbitrary, though.** §7.2 invariant 3 wants "≥3 distinct `city_slug`s
# with ≥2 posts each" and at least one post per `stage`, and the corpus is
# grouped by author — so the number of *authors* is what decides whether those
# values are reachable at all. Eight is the smallest `--users` that reaches a
# `launched`-stage post and a third city; six fails invariant 3 for reasons that
# have nothing to do with the command being wrong. If this file starts failing on
# invariant 3 after a corpus edit, check the author spread before the code.
SEED_ARGS = {"users": 8, "posts": 20, "seed": 20260731, "yes": True, "quiet": True}

# §7.6 — "no username matches ^(test|user|asdf)\\d*$".
THROWAWAY_USERNAME = re.compile(r"^(test|user|asdf|foo|bar|demo)\d*$")
THROWAWAY_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "test.com")


@pytest.fixture
def seeded():
    """One seeded database, shared by the read-only assertions below.

    Seeding is the expensive part of this file, so the tests that only read get
    one run between them. Anything that mutates — `--reset`, the second run of
    the idempotency test — seeds its own.
    """
    call_command("seed_demo", **SEED_ARGS)
    return None


# ── It runs at all ───────────────────────────────────────────────────────────


def test_runs_to_completion_with_small_arguments():
    """§7.6 — "runs to completion with --users 3 --posts 5"."""
    call_command("seed_demo", users=3, posts=5, seed=20260731, yes=True, quiet=True)

    assert User.objects.filter(is_demo=True).exists()
    assert Post.objects.exists()
    assert Comment.objects.exists()


def test_idempotent_second_run_changes_nothing(seeded):
    """§7.6 — "run twice, counts unchanged".

    **This is the test that catches the slug problem** (§7.4.3). `Post.slug` is
    `slugify(title)` plus a random suffix, so the seed cannot know the slug of a
    row it has not created yet: a slug-keyed get-or-create would create a second
    copy of every post on the second run and nothing else in the suite would
    notice. The natural key is `(author, title)`, which the seed fully controls.

    Sparks and saves are counted here for a second reason: the services that
    create them are **toggles**, so an unguarded second run would un-spark the
    entire corpus and these counts would go *down* rather than up.
    """
    before = {
        "users": User.objects.count(),
        "posts": Post.all_objects.count(),
        "comments": Comment.all_objects.count(),
        "sparks": PostSpark.objects.count(),
        "saves": SavedPost.objects.count(),
        "follows": Follow.objects.count(),
        "reports": Report.objects.count(),
    }

    call_command("seed_demo", **SEED_ARGS)

    after = {
        "users": User.objects.count(),
        "posts": Post.all_objects.count(),
        "comments": Comment.all_objects.count(),
        "sparks": PostSpark.objects.count(),
        "saves": SavedPost.objects.count(),
        "follows": Follow.objects.count(),
        "reports": Report.objects.count(),
    }

    assert after == before


# ── The two flags (§7.5) ─────────────────────────────────────────────────────


def test_every_seeded_user_is_demo(seeded):
    """§7.6 — "every created user has is_demo=True"."""
    assert not User.objects.filter(is_demo=False).exists()


def test_exactly_three_accounts_are_public_demo(seeded):
    """§7.6 — the three accounts whose passwords are printed on the login screen."""
    public = set(
        User.objects.filter(is_public_demo=True).values_list("email", flat=True)
    )
    assert public == {
        "demo@alongside.app",
        "demo.new@alongside.app",
        "demo.mod@alongside.app",
    }


def test_no_user_is_public_demo_without_is_demo(seeded):
    """§7.6, and the reason it is asserted rather than assumed.

    > One that did would survive `--reset` and leave published credentials
    > pointing at an account whose data is gone.

    The two flags answer different questions (`data-model.md` §1.1.1):
    `is_demo` is lineage and decides what `--reset` may delete; `is_public_demo`
    is the write restriction. `is_public_demo` without `is_demo` is the one
    combination that is incoherent.
    """
    assert not User.objects.filter(is_public_demo=True, is_demo=False).exists()


def test_seeded_authors_are_not_write_restricted(seeded):
    """The failure v1 of `testing.md` would have shipped.

    Enforcing the write-block off `is_demo` would have made every
    content-authoring seeded user unable to own a post — an empty-looking site,
    which is the exact thing the seed exists to prevent. So: the posts in this
    database are owned by `is_demo` users who are **not** `is_public_demo`.
    """
    authored_by_unrestricted = Post.objects.filter(
        author__is_demo=True, author__is_public_demo=False
    ).count()
    assert authored_by_unrestricted > 0


# ── demo.mod@ — Decision I (§7.5) ────────────────────────────────────────────


def test_demo_mod_is_in_the_group_and_is_not_a_superuser(seeded):
    moderator = User.objects.get(email="demo.mod@alongside.app")

    assert moderator.is_staff is True
    assert moderator.is_superuser is False
    assert [group.name for group in moderator.groups.all()] == [DEMO_MODERATOR_GROUP]


def test_demo_mod_holds_no_delete_permission_on_any_installed_model(seeded):
    """§7.5, and **iterating the models is the point of the test.**

    > the account holds no `delete_*` permission on any model, asserted by
    > iterating every installed model rather than a hand-written list, so a new
    > app can't quietly widen it.

    `is_public_demo` is an application-layer check and **Django admin never
    consults it** — so this account's published password is only safe because of
    what the group does *not* grant. A hand-written list of models would go
    stale the first time somebody adds an app.
    """
    moderator = User.objects.get(email="demo.mod@alongside.app")
    held = moderator.get_all_permissions()

    forbidden = {
        f"{model._meta.app_label}.delete_{model._meta.model_name}"
        for model in apps.get_models()
    }
    assert held.isdisjoint(forbidden), f"demo.mod@ can delete: {held & forbidden}"


def test_demo_mod_can_only_view_and_change_reports(seeded):
    moderator = User.objects.get(email="demo.mod@alongside.app")

    assert moderator.get_all_permissions() == {
        "moderation.view_report",
        "moderation.change_report",
    }


def test_the_moderation_queue_is_not_empty(seeded):
    """§7.5 — "seeded with 2 open reports so the queue isn't empty".

    A moderation queue is the one screen that cannot be demonstrated with an
    empty state, because an empty queue and a broken queue look identical.
    """
    assert Report.objects.filter(status=ReportStatus.OPEN).count() >= 2


# ── --reset (§7.4.1, §7.4.4) ─────────────────────────────────────────────────


def test_reset_deletes_demo_rows_and_leaves_a_real_user_untouched():
    """§7.6 — "--reset deletes demo rows and leaves a non-demo user untouched".

    The scope of `--reset` is `is_demo`, never a `flush` and never a `TRUNCATE`.
    This is the assertion that would fail if somebody "simplified" it.
    """
    real = User.objects.create_user(
        username="jeni", email="jeni@alongside.app", password="pw"
    )
    call_command("seed_demo", **SEED_ARGS)
    assert User.objects.filter(is_demo=True).exists()

    call_command("seed_demo", **SEED_ARGS, reset=True)

    real.refresh_from_db()
    assert real.is_active
    assert real.email == "jeni@alongside.app"
    assert User.objects.filter(pk=real.pk).exists()


def test_reset_leaves_no_stale_counters_and_no_orphans():
    """§7.6 — "--reset leaves no stale counters and no orphans".

    Four separate things, because `--reset` has four ways to leave the database
    smaller but wrong:

    * curated tags and roles survive — `Profile.field_tag` is an FK and the
      onboarding picker needs those rows identical in every environment;
    * non-curated tags that end at zero are gone, so the tag cloud does not read
      "fintech (12)" over no posts;
    * every remaining `Tag.post_count` equals a real count;
    * no `Conversation` is left without participants — deleting a user cascades
      their `ConversationParticipant` row but not the thread, which has no FK to
      a user at all.
    """
    from messaging.models import Conversation

    call_command("seed_demo", **SEED_ARGS)
    curated_tags = set(Tag.objects.filter(is_curated=True).values_list("slug", flat=True))
    curated_roles = set(Role.objects.values_list("slug", flat=True))
    assert curated_tags and curated_roles

    call_command("seed_demo", **SEED_ARGS, reset=True)
    call_command("seed_demo", **SEED_ARGS, reset=True)

    assert set(
        Tag.objects.filter(is_curated=True).values_list("slug", flat=True)
    ) == curated_tags
    assert set(Role.objects.values_list("slug", flat=True)) == curated_roles

    # Only reachable after a reset that removed every post carrying them.
    for tag in Tag.objects.annotate(
        real=Count("post_tags", filter=Q(post_tags__post__deleted_at__isnull=True))
    ):
        assert tag.post_count == tag.real, f"{tag.slug} reads {tag.post_count}"

    assert not Conversation.objects.annotate(n=Count("participants")).filter(n=0).exists()


def test_refuses_without_yes_when_non_demo_users_exist():
    """§7.6 — "refuses without --yes when non-demo users exist".

    This is the check that stops the command being run against production data
    that is not demo data, and it keys on non-demo *users* rather than on row
    counts: a database that has only ever been seeded is safe to re-seed, and
    one with a single real signup is not.
    """
    User.objects.create_user(username="jeni", email="jeni@alongside.app", password="pw")

    with pytest.raises(CommandError, match="non-demo user"):
        call_command("seed_demo", users=3, posts=5, quiet=True)

    assert not Post.objects.exists()


# ── Counters and derived columns (§7.3) ──────────────────────────────────────


def test_counters_equal_real_row_counts(seeded):
    """§7.6 — "counters equal real row counts".

    The seed writes real rows and derives every counter in one pass at the end,
    so it can never ship numbers that disagree with reality — and running the
    seed exercises that reconciliation logic every time (§7.3).
    """
    for post in Post.all_objects.annotate(
        real_sparks=Count("sparks", distinct=True),
        real_comments=Count(
            "comments", filter=Q(comments__deleted_at__isnull=True), distinct=True
        ),
        real_saves=Count("saves", distinct=True),
    ):
        assert post.spark_count == post.real_sparks, post.slug
        assert post.comment_count == post.real_comments, post.slug
        assert post.save_count == post.real_saves, post.slug

    for profile in Profile.objects.annotate(
        real_followers=Count("user__follower_edges", distinct=True),
        real_following=Count("user__following_edges", distinct=True),
        real_posts=Count(
            "user__posts", filter=Q(user__posts__deleted_at__isnull=True), distinct=True
        ),
    ):
        assert profile.follower_count == profile.real_followers, profile.user_id
        assert profile.following_count == profile.real_following, profile.user_id
        assert profile.post_count == profile.real_posts, profile.user_id

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
        assert role.usage_count == role.real_usage, role.slug


def test_no_seeded_row_has_a_null_search_vector(seeded):
    """§7.6, and §7.3 calls this the seed's most likely silent failure.

    `bulk_create` does not fire `post_save`, and the vector is written by an
    explicit call — so anything written in bulk, or anything whose tags changed
    after creation, has a null vector. **Search then returns nothing on the
    deployed site while every unit test of the extractor passes.** The star
    feature failing on the demo because of a bulk insert is not a hypothetical;
    it is the default outcome if nobody asserts this.
    """
    assert not Post.all_objects.filter(search_vector__isnull=True).exists()
    assert not Profile.objects.filter(search_vector__isnull=True).exists()


def test_seeded_posts_are_actually_findable_by_search(seeded):
    """The other half of the same risk.

    A non-null vector built from the wrong text is just as invisible as a null
    one, so this searches for a word from a real corpus title and expects the
    post back. It is the cheapest possible end-to-end proof that the demo's
    search box will return something.
    """
    from discovery.search import search_posts

    crochet = Post.objects.filter(title__icontains="crochet").first()
    assert crochet is not None, "the crochet case is named in product-spec.md §1"

    results = list(search_posts("crochet"))
    assert crochet.pk in {post.pk for post in results}


# ── Dates (§7.2) ─────────────────────────────────────────────────────────────


def test_date_invariants_hold(seeded):
    """§7.6 — "no comment predates its post, last_activity_at >= published_at,
    nothing in the future".

    `last_activity_at >= published_at` is also a real `CheckConstraint`
    (`post_activity_after_publication`), so a violation would raise at insert —
    but the other two are not enforceable in the schema and a seed bug would
    ship quietly. A feed where a comment predates the post it is on is the kind
    of detail a visitor notices without being able to name.
    """
    now = timezone.now()

    assert not Post.all_objects.filter(published_at__gt=now).exists()
    assert not Post.all_objects.filter(last_activity_at__gt=now).exists()
    assert not Post.all_objects.filter(
        last_activity_at__lt=F("published_at")
    ).exists()
    assert not Comment.all_objects.filter(created_at__gt=now).exists()
    assert not Comment.all_objects.filter(
        created_at__lt=F("post__published_at")
    ).exists()
    assert not PostSpark.objects.filter(
        created_at__lt=F("post__published_at")
    ).exists()


def test_post_dates_are_spread_not_all_now(seeded):
    """§7.2 — "a feed where all 45 posts say '2 minutes ago' is more obviously
    fake than lorem ipsum".

    `created_at` is `auto_now_add` and therefore all "now" by construction;
    `published_at` is the writable ordering key that exists so the spread is
    possible (§2.3.1). This asserts the seed actually used it.
    """
    dates = list(Post.objects.values_list("published_at", flat=True))
    spread = max(dates) - min(dates)
    assert spread > timedelta(days=20), f"published_at spans only {spread}"


# ── No throwaway-looking data (§7.6) ─────────────────────────────────────────


def test_nothing_reads_as_throwaway_test_data(seeded):
    """§7.6 — "no post body is empty, no example.com email, no test1 username".

    `product-spec.md` §5.1 puts this in the requirements: "Must look real (not
    `test1`, `asdf@x.com`)". It is the one quality bar on the seed that can be
    expressed mechanically, so it is.
    """
    for user in User.objects.all():
        assert not THROWAWAY_USERNAME.match(user.username), user.username
        domain = user.email.rpartition("@")[2]
        assert domain not in THROWAWAY_EMAIL_DOMAINS, user.email
        assert user.display_name, f"{user.username} renders with no name"

    for post in Post.all_objects.all():
        assert post.body.strip(), post.slug
        assert post.title.strip(), post.slug
        # Lorem ipsum is the specific thing §7.1 exists to prevent.
        assert "lorem ipsum" not in post.body.lower(), post.slug

    for comment in Comment.all_objects.all():
        assert comment.body.strip(), comment.pk


def test_every_post_names_at_least_one_role(seeded):
    """Decision F (Jeni, 3 Oct 2026) — "every post must name at least one role".

    `posts.services.create_post` does not enforce it, the form does — so the
    corpus has to satisfy it, and a post that slipped through with none could
    never be matched or filtered. It would be invisible on the joiner's primary
    path (roadmap §1.3) and perfectly healthy everywhere else.
    """
    roleless = list(
        Post.all_objects.annotate(n=Count("roles_needed")).filter(n=0).values_list(
            "slug", flat=True
        )
    )
    assert not roleless, f"posts with no roles: {roleless}"


def test_the_crochet_case_is_present(seeded):
    """`product-spec.md` §1 names it, so it is the spec's own worked example.

    If it ever vanishes from the corpus, the demo stops being able to
    demonstrate the case the product was pitched on.
    """
    assert Post.objects.filter(title__icontains="crochet").exists()
    assert Tag.objects.filter(slug="craft-small-business", post_count__gt=0).exists()


# ── The three guarantees (§7.2) ──────────────────────────────────────────────


def test_tier_two_data_exists_for_every_demo_account_field_tag(seeded):
    """§7.2 invariant 1 — **the most important assertion in this file.**

    > For every curated field tag assigned to a demo account, the seed
    > guarantees ≥3 posts carrying that tag, published within the last 7 days,
    > with non-zero sparks.

    Sampled from a 90-day spread across ~15 tags the expected count is well under
    one, so this is guaranteed rather than sampled: `demo.new@`, whose entire
    purpose is the cold-start experience, would otherwise fall straight through
    to tier 3 and **the personalisation would be invisible on the live site**.
    The cascade hides that perfectly — Home still looks full, and nothing errors.

    The query mirrors `discovery/feed.py::_tier_2` clause for clause on purpose.
    """
    since = timezone.now() - TIER_2_WINDOW

    for user in User.objects.filter(is_public_demo=True).select_related("profile"):
        field_tag = user.profile.field_tag
        assert field_tag is not None, f"{user.email} has no field_tag"

        qualifying = (
            Post.objects.filter(
                tags=field_tag,
                status=PostStatus.LOOKING,
                published_at__gte=since,
                spark_count__gt=0,
            )
            .exclude(author=user)
            .distinct()
            .count()
        )
        assert qualifying >= 3, (
            f"{user.email}: only {qualifying} post(s) carry {field_tag.slug!r} "
            "inside the 7-day window with sparks — tier 2 will be invisible"
        )


def test_the_cold_start_account_actually_sees_tier_two(seeded):
    """The same invariant, proved through the real cascade rather than a query.

    ADR-0004 requires tier 2 to be asserted *specifically*: tier 3 would satisfy
    "Home is non-empty" while hiding exactly the bug ADR-0004 fixed. So this
    asserts on `section.tier`, and `demo.new@` is the account that forces it —
    it follows nobody and has no interests, so tier 1 cannot fire.
    """
    newcomer = User.objects.get(email="demo.new@alongside.app")

    assert newcomer.following_edges.count() == 0
    assert newcomer.profile.interests.count() == 0

    sections = home_feed(newcomer)
    tiers = {section.tier: section for section in sections}

    assert 2 in tiers, f"tier 2 did not fire; got tiers {sorted(tiers)}"
    assert len(tiers[2].posts) >= 3
    assert tiers[2].label.startswith("Popular in")


def test_every_empty_state_is_reachable(seeded):
    """§7.2 invariant 2.

    > ≥1 post with zero comments, ≥1 with zero sparks, ≥1 user with zero posts,
    > ≥1 user with zero followers.

    Empty states are the most-skipped and most-seen-by-strangers screens in any
    portfolio project (§6), and a demo in which none of them is reachable means
    nobody will ever look at them before a stranger does.
    """
    assert Post.objects.filter(comment_count=0).exists()
    assert Post.objects.filter(spark_count=0).exists()
    assert Profile.objects.filter(post_count=0).exists()
    assert Profile.objects.filter(follower_count=0).exists()


def test_every_filter_option_returns_rows(seeded):
    """§7.2 invariant 3.

    > At least one post for each `stage`, each `commitment`, ≥3 distinct
    > `city_slug`s with ≥2 posts each, and ≥5 curated roles used.

    "A filter dropdown that returns 'no results' for half its options reads as
    broken." `discovery/feed.py::filtered_feed` filters `status=looking` posts
    only, so the counts below are scoped the same way — a filter that matches
    only `team_formed` posts returns nothing in the UI.
    """
    from posts.models import Commitment, Stage

    live = Post.objects.filter(status=PostStatus.LOOKING)

    for stage in Stage.values:
        assert live.filter(stage=stage).exists(), f"no live post at stage {stage}"
    for commitment in Commitment.values:
        assert live.filter(commitment=commitment).exists(), commitment

    cities = (
        live.exclude(city_slug="")
        .values("city_slug")
        .annotate(n=Count("pk"))
        .filter(n__gte=2)
    )
    assert cities.count() >= 3, f"only {cities.count()} city slug(s) with 2+ posts"

    roles_in_use = (
        Role.objects.filter(post_roles__post__status=PostStatus.LOOKING)
        .distinct()
        .count()
    )
    assert roles_in_use >= 5, f"only {roles_in_use} curated role(s) in use"


def test_city_slug_is_populated_so_the_city_filter_works(seeded):
    """Not in §7.6, added because it is a live trap.

    `city_slug` is derived in the **form layer** — nothing in `Post.save()` does
    it — and `filtered_feed(city=...)` matches on the slug, not on `city`. A seed
    that set only the free-text field would produce a location filter where
    every option returns nothing, and the posts would look completely fine.
    """
    with_city = Post.objects.exclude(city="")
    assert with_city.exists()
    assert not with_city.filter(city_slug="").exists()


# ── The distributions (§7.2) ─────────────────────────────────────────────────


def test_engagement_is_lumpy_not_uniform(seeded):
    """§7.2 — "a real community is lumpy".

    > Uniform random data feels wrong in a way people notice but can't name.

    Asserted as a shape rather than as numbers: the most-sparked post is well
    clear of the median, which is what makes the "most sparked" sort meaningful
    and is the property a uniform distribution would not have.
    """
    sparks = sorted(Post.objects.values_list("spark_count", flat=True))
    assert len(sparks) >= 5

    median = sparks[len(sparks) // 2]
    assert sparks[-1] > median, "spark counts are flat — the heavy tail is missing"
    assert sparks[0] == 0, "no post has zero sparks"


def test_posts_per_author_follows_a_power_law(seeded):
    """§7.2 — "2 users post 5-7, most post 1-3, 3 users post 0".

    Shape, not counts: somebody posts materially more than the typical author,
    and somebody posts nothing. A seed that spread posts evenly would give every
    profile the same two cards, which reads as generated.
    """
    counts = sorted(
        Profile.objects.values_list("post_count", flat=True), reverse=True
    )
    assert counts[0] >= 2
    assert counts[-1] == 0, "every seeded user has posts — no empty profile to see"


def test_some_posts_are_already_team_formed(seeded):
    """The brief names this: "a few posts already marked team formed".

    `status` is one of the three anti-ghosting fields (`CONTRIBUTING.md`), so a demo
    where every post is still `looking` fails to show the design the product is
    built around.
    """
    assert Post.objects.filter(status=PostStatus.TEAM_FORMED).exists()
    assert Post.objects.filter(status=PostStatus.LOOKING).count() > Post.objects.filter(
        status=PostStatus.TEAM_FORMED
    ).count()


def test_the_stale_nudge_job_has_something_to_act_on(seeded):
    """§7.2 — "2-3 posts old and untouched, so the nudge job has something real".

    `moderation.tasks.send_nudges` selects on exactly this predicate. A seed
    that left no candidates would make the job a no-op on the deployed site, and
    the nudge is one of three named anti-ghosting countermeasures (spec §4.8) —
    so it would be a feature nobody could see working.
    """
    from moderation.tasks import NUDGE_AFTER

    candidates = Post.objects.filter(
        status=PostStatus.LOOKING,
        is_stale=False,
        nudged_at__isnull=True,
        last_activity_at__lt=timezone.now() - NUDGE_AFTER,
    )
    assert candidates.count() >= 2


def test_custom_roles_and_free_text_tags_are_both_visible(seeded):
    """§7.1 — the ADR-0004 "Other" path has to appear in the demo.

    Roles are curated because they are exact-match filtered; tags are free text
    because they are matched by search. Both halves of that decision need rows,
    or the demo demonstrates only one of them.
    """
    assert Post.objects.exclude(custom_roles=[]).exists()
    assert Tag.objects.filter(is_curated=False, post_count__gt=0).exists()
    assert Tag.objects.filter(is_curated=True, post_count__gt=0).exists()


# ── The demo account's curated state (§7.5) ──────────────────────────────────


def test_demo_account_has_the_state_the_login_screen_promises(seeded):
    """§7.5 — "3 posts, follows 6 people, 5 saved posts, a curated field_tag".

    This is the account a stranger lands in from the login screen, so every one
    of these is a screen that would otherwise show an empty state to the first
    visitor.
    """
    demo = User.objects.get(email="demo@alongside.app")
    profile = demo.profile

    assert profile.post_count == 3
    assert profile.field_tag is not None
    assert profile.field_tag.is_curated
    assert demo.following_edges.count() >= 5
    assert SavedPost.objects.filter(user=demo).count() >= 5


def test_demo_account_has_unread_notifications(seeded):
    """§7.5 — "4 unread notifications".

    Produced by real follows and real comments rather than written directly, so
    every bell entry links at something that exists. `notifications` 0002's
    `notification_kind_targets` CHECK would reject a hand-made row with the
    wrong FKs, which is the schema backing this up.
    """
    from notifications.models import Notification

    demo = User.objects.get(email="demo@alongside.app")
    assert Notification.objects.filter(recipient=demo, is_read=False).count() >= 4


def test_demo_account_has_two_conversations_with_unread_messages(seeded):
    """§7.5 — "2 conversations with unread messages".

    The `dyad_key` is asserted because `dyad_key_for()` zero-pads to 19 digits
    and is the only place the key may be formatted (M11): a string-sorted
    implementation writes `"10:9"` for one caller and `"9:10"` for the other,
    both inserts succeed, and the unique constraint stops preventing the
    duplicate thread it exists to prevent — starting at exactly the user ids a
    20-user seed reaches.
    """
    from messaging.models import ConversationParticipant, dyad_key_for

    demo = User.objects.get(email="demo@alongside.app")
    participations = list(
        ConversationParticipant.objects.filter(user=demo).select_related("conversation")
    )

    assert len(participations) == 2
    assert all(participation.unread_count > 0 for participation in participations)

    for participation in participations:
        conversation = participation.conversation
        other = (
            ConversationParticipant.objects.filter(conversation=conversation)
            .exclude(user=demo)
            .get()
        )
        assert conversation.dyad_key == dyad_key_for(demo.pk, other.user_id)
        assert conversation.last_message_at is not None
        assert conversation.last_message_preview
        # GAP 11 / M5 — the context strip answers "why is this person messaging
        # me", and it cannot do that without an origin post.
        assert conversation.origin_post_id is not None


def test_the_cold_start_account_is_genuinely_cold(seeded):
    """§7.5 — "no follows, no interests, no posts".

    A single follow edge on this account collapses Home tier 1 back into
    existence and hides tier 2 — the star feature — from the one visitor most
    likely to look at it.
    """
    newcomer = User.objects.get(email="demo.new@alongside.app")

    assert newcomer.following_edges.count() == 0
    assert newcomer.follower_edges.count() == 0
    assert newcomer.profile.interests.count() == 0
    assert newcomer.posts.count() == 0
    assert newcomer.profile.onboarding_completed_at is None
    # But a field tag IS set, because that is what tier 2 matches on.
    assert newcomer.profile.field_tag is not None
