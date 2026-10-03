"""The Home cascade — spec §4.3, and the one tier that has silently broken before.

`testing.md` §3 is explicit about how to test this:

> QA must assert **tier 2 specifically returns rows**, not merely that Home is
> non-empty — tier 3 would satisfy the weaker assertion while hiding exactly the
> bug ADR-0004 fixed.

That bug was a `Tag.kind` column splitting "field tags" from "topic tags" into
disjoint sets, so "most-sparked posts carrying your field tag" matched nothing,
forever, with no error anywhere. Every test here that touches tier 2 asserts on
`section.tier`, never on "Home has posts".
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import services as accounts_services
from accounts.models import ProfileInterest
from discovery.feed import home_feed
from posts.models import Post, PostStatus, Tag

pytestmark = pytest.mark.django_db


def make_user(django_user_model, username):
    return django_user_model.objects.create_user(
        username=username, email=f"{username}@example.com", password="pw"
    )


@pytest.fixture
def viewer(django_user_model):
    return make_user(django_user_model, "jeni_dev")


@pytest.fixture
def author(django_user_model):
    return make_user(django_user_model, "ananya_iyer")


@pytest.fixture
def design(db):
    return Tag.objects.filter(is_curated=True).order_by("pk").first()


def make_post(author, title, *, tags=(), sparks=0, published=None, status=PostStatus.LOOKING):
    post = Post.objects.create(
        author=author,
        title=title,
        slug=title.lower().replace(" ", "-")[:140],
        body="Body text for " + title,
        stage="idea",
        commitment="casual",
        status=status,
        spark_count=sparks,
        published_at=published or timezone.now(),
        last_activity_at=published or timezone.now(),
    )
    for tag in tags:
        post.tags.add(tag)
    return post


# ── Tier 1 ──────────────────────────────────────────────────────────────────


def test_tier_1_shows_posts_by_people_you_follow(viewer, author):
    make_post(author, "An idea from somebody I follow")
    accounts_services.follow(viewer, author)

    sections = home_feed(viewer)

    assert sections[0].tier == 1
    assert [p.title for p in sections[0].posts] == ["An idea from somebody I follow"]
    assert sections[0].label == "From people and topics you follow"


def test_tier_1_also_shows_posts_carrying_your_interests(viewer, author, design):
    make_post(author, "An idea tagged with my interest", tags=[design])
    ProfileInterest.objects.create(profile=viewer.profile, tag=design)

    sections = home_feed(viewer)

    assert sections[0].tier == 1
    assert sections[0].posts[0].title == "An idea tagged with my interest"


def test_tier_1_never_shows_you_your_own_posts(viewer, author):
    make_post(viewer, "My own idea")
    make_post(author, "Somebody else's idea")
    accounts_services.follow(viewer, author)

    tier_1 = home_feed(viewer)[0]

    assert tier_1.tier == 1
    assert [p.title for p in tier_1.posts] == ["Somebody else's idea"]


# ── Tier 2 — the one ADR-0004 exists for ────────────────────────────────────


def test_tier_2_returns_rows_for_your_field(viewer, author, design):
    """The assertion `testing.md` §3 asks for by name.

    Asserting "Home is non-empty" would pass here on tier 3 while tier 2
    returned nothing — which is precisely the failure that shipped silently in
    the first draft of the schema.
    """
    viewer.profile.field_tag = design
    viewer.profile.save(update_fields=["field_tag"])
    make_post(author, "A popular idea in my field", tags=[design], sparks=42)

    sections = home_feed(viewer)

    tier_2 = [s for s in sections if s.tier == 2]
    assert tier_2, "tier 2 returned no rows — ADR-0004's bug is back"
    assert tier_2[0].posts[0].title == "A popular idea in my field"
    assert tier_2[0].label == f"Popular in {design.name} this week"


def test_tier_2_is_sorted_by_sparks(viewer, author, design):
    viewer.profile.field_tag = design
    viewer.profile.save(update_fields=["field_tag"])
    make_post(author, "Quietly good", tags=[design], sparks=3)
    make_post(author, "Everybody sparked this", tags=[design], sparks=99)

    tier_2 = [s for s in home_feed(viewer) if s.tier == 2][0]

    assert [p.title for p in tier_2.posts] == ["Everybody sparked this", "Quietly good"]


def test_tier_2_is_this_week_only(viewer, author, design):
    """The label says "this week" — the query has to keep that promise."""
    viewer.profile.field_tag = design
    viewer.profile.save(update_fields=["field_tag"])
    old = timezone.now() - timedelta(days=30)
    make_post(author, "Popular but a month old", tags=[design], sparks=99, published=old)

    sections = home_feed(viewer)

    assert [s.tier for s in sections] == [3]


# ── Tier 3 ──────────────────────────────────────────────────────────────────


def test_a_brand_new_account_still_gets_a_feed(viewer, author):
    """The cold-start case. An empty Home is how a portfolio demo dies."""
    make_post(author, "Something to look at")

    sections = home_feed(viewer)

    assert sections[0].tier == 3
    assert sections[0].posts
    # Labelled, or it reads as a broken personalised feed rather than a
    # deliberate fallback.
    assert sections[0].label == "Fresh ideas"


def test_tier_3_does_show_you_your_own_post(viewer):
    """A new user's only post disappearing from Home reads as "it didn't save"."""
    make_post(viewer, "The one thing I posted")

    sections = home_feed(viewer)

    assert [p.title for p in sections[0].posts] == ["The one thing I posted"]


# ── The cascade itself ──────────────────────────────────────────────────────


def test_a_post_never_appears_in_two_tiers(viewer, author, design):
    """Tiers exclude what the ones above them already showed."""
    viewer.profile.field_tag = design
    viewer.profile.save(update_fields=["field_tag"])
    ProfileInterest.objects.create(profile=viewer.profile, tag=design)
    make_post(author, "Matches tier 1 and tier 2", tags=[design], sparks=50)

    sections = home_feed(viewer)

    seen = [post.pk for section in sections for post in section.posts]
    assert len(seen) == len(set(seen))


def test_lower_tiers_are_skipped_once_the_page_is_full(viewer, author):
    accounts_services.follow(viewer, author)
    for n in range(3):
        make_post(author, f"Idea number {n}")

    sections = home_feed(viewer, limit=3)

    assert [s.tier for s in sections] == [1]


def test_team_formed_posts_are_not_on_home(viewer, author):
    accounts_services.follow(viewer, author)
    make_post(author, "Already has a team", status=PostStatus.TEAM_FORMED)
    make_post(author, "Still looking")

    titles = [p.title for s in home_feed(viewer) for p in s.posts]

    assert titles == ["Still looking"]


def test_home_filters_blocked_authors(viewer, author):
    """ADR-0002 — and Home is the screen most likely to surface somebody."""
    make_post(author, "From somebody I blocked")
    accounts_services.block(viewer, author)

    titles = [p.title for s in home_feed(viewer) for p in s.posts]

    assert titles == []


# ── The screen ──────────────────────────────────────────────────────────────


def test_home_requires_signing_in(client):
    """The one feed that does. Everything else is public (rule 7)."""
    response = client.get(reverse("posts:home"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_home_renders_its_labelled_dividers(client, viewer, author):
    make_post(author, "Something to look at")
    client.force_login(viewer)

    body = client.get(reverse("posts:home")).content.decode()

    assert "Fresh ideas" in body
    assert "Something to look at" in body


def test_home_prompts_an_unfinished_onboarding(client, viewer, author):
    make_post(author, "Something to look at")
    client.force_login(viewer)

    body = client.get(reverse("posts:home")).content.decode()

    assert "Set up my feed" in body

    viewer.profile.onboarding_completed_at = timezone.now()
    viewer.profile.save(update_fields=["onboarding_completed_at"])
    assert "Set up my feed" not in client.get(reverse("posts:home")).content.decode()
