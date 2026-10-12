"""Full-text search, keyword extraction, and the filters.

Search is public (`CONTRIBUTING.md` rule 7) and covers posts **and people**
(spec §4.3), deliberately not comments (§9 Q11).

The accent test is the one worth explaining. `accounts` 0002 creates an
`english_unaccent` text search configuration for a reason D1 found the hard
way: under plain `english`, searching "cafe" does not match "café", and in a
corpus of Indian names and places that is not an edge case. Using the wrong
configuration name fails *silently* — the query just returns less — so there is
a test pinning it.
"""

import pytest
from django.urls import reverse

from accounts import services as accounts_services
from discovery.keywords import extract_keywords, keywords_for_post
from discovery.search import search_people, search_posts
from posts import services as post_services
from posts.models import Post, PostStatus, Role

pytestmark = pytest.mark.django_db


def make_user(django_user_model, username, **profile):
    user = django_user_model.objects.create_user(
        username=username, email=f"{username}@example.com", password="pw"
    )
    if profile:
        for field, value in profile.items():
            setattr(user.profile, field, value)
        user.profile.save()
        from discovery.search import refresh_profile_search_vector

        refresh_profile_search_vector(user.profile)
    return user


@pytest.fixture
def author(django_user_model):
    return make_user(django_user_model, "ananya_iyer")


@pytest.fixture
def role():
    return Role.objects.filter(is_curated=True).order_by("pk").first()


def publish(author, title, body="", **kwargs):
    return post_services.create_post(
        author,
        title=title,
        body=body or "Some body text.",
        stage="idea",
        commitment="casual",
        **kwargs,
    )


# ── Keyword extraction (no database) ────────────────────────────────────────


def test_keywords_drop_noise_and_keep_order():
    keywords = extract_keywords("An app that moves leftover canteen food")

    assert keywords == ["app", "moves", "leftover", "canteen", "food"]


def test_keywords_fold_accents_and_case():
    """Must agree with `english_unaccent`, or the keyword never matches."""
    assert extract_keywords("Café CAFÉ cafe") == ["cafe"]


def test_product_noise_words_are_dropped():
    """"Idea", "project" and "team" are on every post here, so they match
    everything, which means they match nothing."""
    assert extract_keywords("my idea for a project with a team") == []


def test_keywords_keep_non_latin_script():
    """The demo corpus is Indian — tokenising Kannada away would make the
    flagship seeded post unfindable in its own language."""
    assert "ಕನ್ನಡ" in extract_keywords("ಕನ್ನಡ OCR for land records")


def test_curated_role_names_are_in_the_keywords():
    """§2.3 — without this, searching "illustrator" finds the post where
    somebody typed it freehand and misses every post that correctly selected
    the curated role. The author who filled the form in properly becomes the
    unfindable one."""
    keywords = keywords_for_post(
        title="A picture book about trees", body="x", roles=["Illustrator"]
    )

    assert "illustrator" in keywords


# ── Searching posts ─────────────────────────────────────────────────────────


def test_search_finds_a_post_by_its_title(author, role):
    publish(author, "An app that moves leftover canteen food", roles=[role])

    results = search_posts("canteen food")

    assert [p.title for p in results] == ["An app that moves leftover canteen food"]


def test_search_finds_a_post_by_its_body(author, role):
    publish(author, "A logistics thing", body="Restaurants throw away biryani every night.",
            roles=[role])

    assert search_posts("biryani").count() == 1


def test_search_finds_a_post_by_a_curated_role_it_asked_for(author, role):
    publish(author, "Something unrelated in its wording", roles=[role])

    assert search_posts(role.name).count() == 1


def test_search_finds_a_post_by_a_custom_other_role(author, role):
    """ADR-0004's bargain: "Other" roles are searchable, never filterable."""
    publish(author, "A picture book", roles=[role], custom_roles=["Kannada copywriter"])

    assert search_posts("kannada copywriter").count() == 1


def test_search_is_accent_insensitive(author, role):
    """D1 — reproduced, and the reason `english_unaccent` exists."""
    publish(author, "A cafe discovery app for Bengaluru", roles=[role])

    assert search_posts("café").count() == 1


def test_title_outranks_body(author, role):
    """Weight A over weight C — the whole reason the vector is weighted."""
    publish(author, "Composting for apartment blocks", roles=[role])
    publish(author, "A delivery app", body="We might add composting later.", roles=[role])

    assert [p.title for p in search_posts("composting")][0] == "Composting for apartment blocks"


def test_an_empty_query_returns_nothing_rather_than_everything(author, role):
    publish(author, "An idea", roles=[role])

    assert search_posts("").count() == 0
    assert search_posts("   ").count() == 0


def test_search_does_not_crash_on_punctuation(author, role):
    """`websearch` never raises on malformed input — a stray quote in the search
    box must not be a 500."""
    publish(author, "An idea", roles=[role])

    assert search_posts('"unclosed quote').count() == 0


def test_search_hides_blocked_authors(author, role, django_user_model):
    viewer = make_user(django_user_model, "jeni_dev")
    publish(author, "An app for canteen food", roles=[role])
    accounts_services.block(viewer, author)

    assert search_posts("canteen", viewer).count() == 0


def test_search_hides_deleted_posts(author, role):
    post = publish(author, "An app for canteen food", roles=[role])
    post_services.soft_delete_post(post)

    assert search_posts("canteen").count() == 0


# ── Searching people ────────────────────────────────────────────────────────


def test_search_finds_people_by_what_they_do(django_user_model):
    make_user(django_user_model, "dev_krishnan", occupation="Android developer, 2 yrs Kotlin")

    assert search_people("kotlin").count() == 1


def test_search_finds_people_by_handle(django_user_model):
    """A unique btree serves equality, not ILIKE '%jen%' — people search by
    handle, which is what the trigram indexes are for (D4)."""
    make_user(django_user_model, "jeni_dev", headline="Builder")

    assert search_people("jeni").count() == 1


def test_people_search_excludes_deleted_accounts(django_user_model):
    user = make_user(django_user_model, "gone_away", occupation="Illustrator")
    from django.utils import timezone

    user.anonymised_at = timezone.now()
    user.save(update_fields=["anonymised_at"])

    assert search_people("illustrator").count() == 0


# ── The screen ──────────────────────────────────────────────────────────────


def test_search_works_signed_out(client, author, role):
    publish(author, "An app that moves leftover canteen food", roles=[role])

    response = client.get(reverse("discovery:search"), {"q": "canteen"})

    assert response.status_code == 200
    assert "An app that moves leftover canteen food" in response.content.decode()


def test_search_names_the_query_when_nothing_matches(client):
    body = client.get(reverse("discovery:search"), {"q": "zzzznothing"}).content.decode()

    assert "Nothing matches that yet" in body
    # Never blames the user (§4.5 rule 3).
    assert "You have no" not in body


# ── Filters ─────────────────────────────────────────────────────────────────


def test_the_feed_filters_by_role(client, author, role):
    second = Role.objects.filter(is_curated=True).exclude(pk=role.pk).first()
    publish(author, "Needs the first role", roles=[role])
    publish(author, "Needs the second role", roles=[second])

    body = client.get(reverse("posts:feed"), {"role": role.slug}).content.decode()

    assert "Needs the first role" in body
    assert "Needs the second role" not in body


def test_the_feed_filters_by_stage_and_commitment(client, author, role):
    publish(author, "A weekend doodle", roles=[role])
    post_services.update_post(Post.objects.get(title="A weekend doodle"), commitment="serious")

    body = client.get(reverse("posts:feed"), {"commitment": "casual"}).content.decode()

    assert "A weekend doodle" not in body


def test_filters_blame_themselves_when_nothing_matches(client, author, role):
    publish(author, "An idea", roles=[role])

    body = client.get(reverse("posts:feed"), {"role": "nonexistent-role"}).content.decode()

    assert "No ideas match those filters" in body
    assert "Clear filters" in body


def test_sorting_by_sparks(client, author, role):
    publish(author, "Quietly good", roles=[role])
    publish(author, "Everybody sparked this", roles=[role])
    Post.objects.filter(title="Everybody sparked this").update(spark_count=99)

    body = client.get(reverse("posts:feed"), {"sort": "sparked"}).content.decode()

    assert body.index("Everybody sparked this") < body.index("Quietly good")


def test_the_feed_is_public(client, author, role):
    publish(author, "An idea anyone can read", roles=[role])

    assert client.get(reverse("posts:feed")).status_code == 200


def test_team_formed_posts_leave_the_feed(client, author, role):
    post = publish(author, "Already has a team", roles=[role])
    post_services.set_status(post, PostStatus.TEAM_FORMED)

    assert "Already has a team" not in client.get(reverse("posts:feed")).content.decode()
