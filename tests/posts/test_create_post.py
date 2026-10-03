"""Publishing, editing and deleting an idea.

The form is the one screen where losing the user costs most, and the service
behind it touches four counters, two M2M tables, a slug that must never change,
and the search vector. The tests are grouped by what breaks:

- **Decision F** — a post must name at least one role (Jeni, 3 Oct 2026)
- **The slug** — generated once, never regenerated, or every link to the post rots
- **Counters** — `Profile.post_count`, `Tag.post_count`, `Role.usage_count`, by
  difference on edit rather than by re-adding
- **`Role.usage_count` means live posts** (PF-6a), so status changes move it and
  the other two counters stay put
- **Ownership** — somebody else's idea is a 404, with no `if` to forget
"""

import pytest
from django.urls import reverse

from accounts.models import Profile
from posts import services
from posts.models import Post, PostStatus, Role, Tag

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )


@pytest.fixture
def other(django_user_model):
    return django_user_model.objects.create_user(
        username="dev_krishnan", email="d@example.com", password="pw"
    )


@pytest.fixture
def role():
    """A curated role from the seeded vocabulary (posts 0002)."""
    return Role.objects.filter(is_curated=True).order_by("pk").first()


@pytest.fixture
def second_role(role):
    return Role.objects.filter(is_curated=True).exclude(pk=role.pk).order_by("pk").first()


def form_data(role, **overrides):
    data = {
        "title": "An app that moves leftover canteen food before it spoils",
        "body": "Restaurants have food left at closing and nobody to take it.",
        "stage": "idea",
        "commitment": "serious",
        "city": "Bengaluru",
        "roles": [str(role.pk)],
        "custom_roles": "",
        "tags": "food waste, logistics",
    }
    data.update(overrides)
    return data


# ── Publishing ──────────────────────────────────────────────────────────────


def test_publishing_an_idea(client, author, role):
    client.force_login(author)

    response = client.post(reverse("posts:create"), form_data(role))

    post = Post.objects.get()
    assert response.status_code == 302
    assert response["Location"] == post.get_absolute_url()
    assert post.author == author
    assert post.city == "Bengaluru"
    # No drafts (§2.3.1) — it is live immediately.
    assert post.status == PostStatus.LOOKING
    assert list(post.roles_needed.all()) == [role]
    assert sorted(post.tags.values_list("name", flat=True)) == ["food waste", "logistics"]


def test_the_create_page_renders(client, author):
    client.force_login(author)

    response = client.get(reverse("posts:create"))

    assert response.status_code == 200
    # The role picker is grouped by category, not a flat list of 41 checkboxes.
    assert response.context["roles_by_category"]


def test_publishing_requires_signing_in(client, role):
    response = client.post(reverse("posts:create"), form_data(role))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert Post.objects.count() == 0


def test_the_public_demo_account_cannot_post(client, django_user_model, role):
    """§1.1.1 — the shared login may spark and save, not add content."""
    demo = django_user_model.objects.create_user(
        username="demo_account", email="demo@example.com", password="pw", is_public_demo=True
    )
    client.force_login(demo)

    response = client.post(reverse("posts:create"), form_data(role))

    assert response.status_code == 302
    assert Post.objects.count() == 0


# ── Decision F ──────────────────────────────────────────────────────────────


def test_an_idea_with_no_roles_is_rejected(client, author, role):
    client.force_login(author)

    response = client.post(reverse("posts:create"), form_data(role, roles=[]))

    assert response.status_code == 200
    assert Post.objects.count() == 0
    assert "roles" in response.context["form"].errors


def test_a_custom_role_alone_satisfies_decision_f(client, author, role):
    """The "Other" box exists for the person who knows exactly what they need
    and finds it missing from our list. Rejecting them would be perverse."""
    client.force_login(author)

    response = client.post(
        reverse("posts:create"), form_data(role, roles=[], custom_roles="Kannada copywriter")
    )

    assert response.status_code == 302
    assert Post.objects.get().custom_roles == ["Kannada copywriter"]


def test_tags_are_optional(client, author, role):
    client.force_login(author)

    response = client.post(reverse("posts:create"), form_data(role, tags=""))

    assert response.status_code == 302
    assert Post.objects.get().tags.count() == 0


def test_caps_are_enforced(client, author, role):
    client.force_login(author)

    response = client.post(
        reverse("posts:create"),
        form_data(role, tags="a, b, c, d, e, f", custom_roles="one, two, three, four"),
    )

    assert response.status_code == 200
    errors = response.context["form"].errors
    assert "tags" in errors
    assert "custom_roles" in errors


# ── Tags (ADR-0004) ─────────────────────────────────────────────────────────


def test_tags_are_created_on_demand_and_matched_on_slug(client, author, role):
    """Free text, deduplicated on slug: "Food Waste" and "food waste" are one
    tag, or the vocabulary fragments into near-duplicates nothing joins up."""
    client.force_login(author)
    client.post(reverse("posts:create"), form_data(role, tags="Food Waste"))

    second = form_data(role, title="A second idea about the same thing", tags="food waste")
    client.post(reverse("posts:create"), second)

    tag = Tag.objects.get(slug="food-waste")
    assert tag.post_count == 2
    assert tag.is_curated is False  # only seeded tags appear in the field picker


# ── The slug ────────────────────────────────────────────────────────────────


def test_slug_is_unique_for_identical_titles(author, role):
    """Titles here are sentences, so collisions are likely and `slug` is unique."""
    first = services.create_post(author, title="The same title", body="x", stage="idea",
                                 commitment="casual", roles=[role])
    second = services.create_post(author, title="The same title", body="y", stage="idea",
                                  commitment="casual", roles=[role])

    assert first.slug != second.slug
    assert first.slug.startswith("the-same-title-")


def test_editing_the_title_does_not_change_the_slug(client, author, role):
    """Otherwise every link, notification and pasted URL rots."""
    post = services.create_post(author, title="First title", body="x", stage="idea",
                                commitment="casual", roles=[role])
    original = post.slug
    client.force_login(author)

    client.post(reverse("posts:edit", args=[post.slug]), form_data(role, title="A better title"))

    post.refresh_from_db()
    assert post.title == "A better title"
    assert post.slug == original


def test_a_title_that_slugifies_to_nothing_still_publishes(author, role):
    post = services.create_post(author, title="಼಼಼", body="x", stage="idea",
                                commitment="casual", roles=[role])

    assert post.slug
    assert post.get_absolute_url()


# ── Counters (§7) ───────────────────────────────────────────────────────────


def test_publishing_moves_three_counters(author, role):
    services.create_post(author, title="An idea", body="x", stage="idea",
                         commitment="casual", roles=[role], tags=["food waste"])

    assert Profile.objects.get(user=author).post_count == 1
    assert Tag.objects.get(slug="food-waste").post_count == 1
    role.refresh_from_db()
    assert role.usage_count == 1


def test_editing_moves_tag_counts_by_difference(client, author, role):
    """The naive "+1 for every current tag" leaves `Tag.post_count` climbing on
    every edit — invisible until a tag page shows twice its real size."""
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role], tags=["keep", "drop"])
    client.force_login(author)

    client.post(reverse("posts:edit", args=[post.slug]), form_data(role, tags="keep, add"))

    assert Tag.objects.get(slug="keep").post_count == 1
    assert Tag.objects.get(slug="drop").post_count == 0
    assert Tag.objects.get(slug="add").post_count == 1


def test_editing_roles_moves_usage_count_by_difference(client, author, role, second_role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])
    client.force_login(author)

    client.post(reverse("posts:edit", args=[post.slug]), form_data(second_role))

    role.refresh_from_db()
    second_role.refresh_from_db()
    assert role.usage_count == 0
    assert second_role.usage_count == 1


def test_an_edit_revives_a_stale_post(client, author, role):
    """An author edit is one of the three activity bumps — a direct statement
    that they are still paying attention."""
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])
    Post.objects.filter(pk=post.pk).update(is_stale=True)
    client.force_login(author)

    client.post(reverse("posts:edit", args=[post.slug]), form_data(role))

    post.refresh_from_db()
    assert post.is_stale is False


# ── Status (PF-6a) ──────────────────────────────────────────────────────────


def test_team_formed_releases_the_role_but_keeps_the_post_counts(author, role):
    """`Role.usage_count` counts LIVE posts requesting the role; a team-formed
    post is not requesting anything. `post_count` counts posts that exist."""
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role], tags=["food waste"])

    services.set_status(post, PostStatus.TEAM_FORMED)

    role.refresh_from_db()
    assert role.usage_count == 0
    assert Profile.objects.get(user=author).post_count == 1
    assert Tag.objects.get(slug="food-waste").post_count == 1


def test_coming_back_to_looking_re_counts_the_role_and_revives_the_post(author, role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])
    services.set_status(post, PostStatus.CLOSED)
    Post.objects.filter(pk=post.pk).update(is_stale=True)

    services.set_status(post, PostStatus.LOOKING)

    role.refresh_from_db()
    post.refresh_from_db()
    assert role.usage_count == 1
    assert post.is_stale is False


def test_status_endpoint_rejects_a_value_that_is_not_a_status(client, author, role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])
    client.force_login(author)

    response = client.post(reverse("posts:set_status", args=[post.slug]), {"status": "banana"})

    assert response.status_code == 404


# ── Deleting ────────────────────────────────────────────────────────────────


def test_deleting_is_soft_and_releases_every_counter(client, author, role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role], tags=["food waste"])
    client.force_login(author)

    response = client.post(reverse("posts:delete", args=[post.slug]))

    assert response.status_code == 302
    # Soft: the row survives for a report that may point at it (§8).
    assert Post.all_objects.filter(pk=post.pk).exists()
    assert Post.objects.filter(pk=post.pk).exists() is False
    assert Profile.objects.get(user=author).post_count == 0
    assert Tag.objects.get(slug="food-waste").post_count == 0
    role.refresh_from_db()
    assert role.usage_count == 0


def test_deleting_twice_moves_the_counters_once(author, role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])

    assert services.soft_delete_post(post) is True
    assert services.soft_delete_post(post) is False

    assert Profile.objects.get(user=author).post_count == 0


def test_you_cannot_edit_or_delete_somebody_elses_idea(client, author, other, role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])
    client.force_login(other)

    assert client.get(reverse("posts:edit", args=[post.slug])).status_code == 404
    assert client.post(reverse("posts:delete", args=[post.slug])).status_code == 404
    assert Post.objects.filter(pk=post.pk).exists()


def test_a_deleted_idea_is_gone_from_the_feed_and_its_own_page(client, author, role):
    post = services.create_post(author, title="An idea", body="x", stage="idea",
                                commitment="casual", roles=[role])
    services.soft_delete_post(post)

    assert client.get(post.get_absolute_url()).status_code == 404
    assert post.title not in client.get(reverse("posts:feed")).content.decode()
