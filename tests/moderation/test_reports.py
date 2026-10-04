"""Reporting — the anti-brigading constraint, and the snapshot that outlives an edit.

Two rules do the real work here and both are easy to get subtly wrong:

1. **One UNRESOLVED report per person per target.** Conditional on
   `status__in=(open, reviewing)`, so a dismissal does not permanently disable
   reporting that target again — which is what the constraint means without the
   condition (§9.1 finding 2).
2. **`target_snapshot`** (TS-3, ruled in by Jeni 3 Oct 2026). Posts are
   editable; without a copy taken at report time, somebody can post something
   abusive, get reported, and edit it innocuous before anyone looks.

Decision H — signing in is required — is what gives rule 1 a person to key on.
"""

import pytest
from django.urls import reverse

from moderation.models import Report, ReportStatus
from posts import services as post_services
from posts.models import Role
from social import services as social_services

pytestmark = pytest.mark.django_db


@pytest.fixture
def author(django_user_model):
    return django_user_model.objects.create_user(
        username="ananya_iyer", email="a@example.com", password="pw"
    )


@pytest.fixture
def reporter(django_user_model):
    return django_user_model.objects.create_user(
        username="jeni_dev", email="j@example.com", password="pw"
    )


@pytest.fixture
def post(author):
    return post_services.create_post(
        author,
        title="An idea somebody objects to",
        body="The body of it.",
        stage="idea",
        commitment="casual",
        roles=[Role.objects.filter(is_curated=True).first()],
    )


def report_url(post):
    return reverse("moderation:report_post", kwargs={"slug": post.slug})


# ── Filing one ──────────────────────────────────────────────────────────────


def test_reporting_a_post(client, post, reporter):
    client.force_login(reporter)

    response = client.post(report_url(post), {"reason": "spam", "details": "Posted ten times."})

    assert response.status_code == 302
    report = Report.objects.get()
    assert report.reporter == reporter
    assert report.post == post
    assert report.status == ReportStatus.OPEN


def test_reporting_requires_signing_in(client, post):
    """Decision H — the constraint needs somebody to key on."""
    response = client.post(report_url(post), {"reason": "spam"})

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert Report.objects.count() == 0


def test_reporting_a_comment(client, post, author, reporter):
    comment = social_services.add_comment(author, post, "Something objectionable.")
    client.force_login(reporter)

    client.post(
        reverse("moderation:report_comment", kwargs={"pk": comment.pk}), {"reason": "harassment"}
    )

    assert Report.objects.get().comment == comment


def test_reporting_a_person(client, author, reporter):
    client.force_login(reporter)

    client.post(
        reverse("moderation:report_user", kwargs={"username": author.username}),
        {"reason": "impersonation"},
    )

    assert Report.objects.get().reported_user == author


def test_you_cannot_report_yourself(client, author):
    client.force_login(author)

    response = client.post(
        reverse("moderation:report_user", kwargs={"username": author.username}),
        {"reason": "spam"},
    )

    assert response.status_code == 404


def test_other_requires_an_explanation(client, post, reporter):
    """A queue full of bare "other" is a queue nobody can work."""
    client.force_login(reporter)

    response = client.post(report_url(post), {"reason": "other", "details": ""})

    assert response.status_code == 200
    assert Report.objects.count() == 0
    assert "details" in response.context["form"].errors


# ── The anti-brigading constraint ───────────────────────────────────────────


def test_reporting_the_same_thing_twice_is_not_an_error(client, post, reporter):
    """`IntegrityError` is the normal path here, caught rather than pre-checked —
    a check-then-insert is a race two taps on a phone will lose."""
    client.force_login(reporter)

    client.post(report_url(post), {"reason": "spam"})
    response = client.post(report_url(post), {"reason": "scam"})

    assert response.status_code == 302
    assert Report.objects.count() == 1


def test_you_can_report_again_once_a_report_is_resolved(client, post, reporter):
    """The condition on the constraint, and the whole point of it: without it,
    one dismissal permanently disables reporting that target ever again."""
    client.force_login(reporter)
    client.post(report_url(post), {"reason": "spam"})
    Report.objects.update(status=ReportStatus.DISMISSED)

    client.post(report_url(post), {"reason": "harassment"})

    assert Report.objects.count() == 2


def test_two_people_can_report_the_same_thing(client, post, reporter, django_user_model):
    other = django_user_model.objects.create_user(
        username="dev_krishnan", email="d@example.com", password="pw"
    )
    client.force_login(reporter)
    client.post(report_url(post), {"reason": "spam"})

    client.force_login(other)
    client.post(report_url(post), {"reason": "spam"})

    assert Report.objects.count() == 2


def test_one_person_can_report_two_different_things(client, post, author, reporter):
    """The three unique constraints coexist only because NULL is distinct —
    TS-4. Collapse that and one person could only ever report one thing."""
    client.force_login(reporter)

    client.post(report_url(post), {"reason": "spam"})
    client.post(
        reverse("moderation:report_user", kwargs={"username": author.username}),
        {"reason": "harassment"},
    )

    assert Report.objects.count() == 2


# ── The snapshot (TS-3) ─────────────────────────────────────────────────────


def test_the_snapshot_survives_an_edit(client, post, author, reporter):
    """The reason the column exists. Edit the post after it is reported and the
    moderator still sees what was actually reported."""
    client.force_login(reporter)
    client.post(report_url(post), {"reason": "harassment"})

    post_services.update_post(post, title="Something innocuous now", body="Nothing to see.")

    report = Report.objects.get()
    assert "An idea somebody objects to" in report.target_snapshot
    assert "The body of it." in report.target_snapshot
    post.refresh_from_db()
    assert post.title == "Something innocuous now"


def test_the_snapshot_survives_a_deletion(client, post, reporter):
    """Posts are soft-deleted precisely so a report keeps its evidence (§8) —
    and the snapshot means the moderator can read it without digging."""
    client.force_login(reporter)
    client.post(report_url(post), {"reason": "spam"})

    post_services.soft_delete_post(post)

    report = Report.objects.get()
    assert report.post is not None  # soft, so the FK still resolves
    assert "An idea somebody objects to" in report.target_snapshot


def test_a_comment_snapshot_is_its_body(client, post, author, reporter):
    comment = social_services.add_comment(author, post, "The exact words used.")
    client.force_login(reporter)

    client.post(
        reverse("moderation:report_comment", kwargs={"pk": comment.pk}), {"reason": "harassment"}
    )

    assert Report.objects.get().target_snapshot == "The exact words used."


# ── Rate limiting ───────────────────────────────────────────────────────────


def test_reports_are_rate_limited(client, author, reporter, django_user_model, settings):
    """The moderation-DoS guard. The unique constraint stops duplicate reports
    of one target; nothing else stops fifty reports of fifty targets."""
    from django.core.cache import cache

    cache.clear()
    client.force_login(reporter)

    # 20/h, so the 21st distinct target is refused.
    targets = [
        django_user_model.objects.create_user(
            username=f"person_{n}", email=f"p{n}@example.com", password="pw"
        )
        for n in range(21)
    ]
    statuses = [
        client.post(
            reverse("moderation:report_user", kwargs={"username": person.username}),
            {"reason": "spam"},
        ).status_code
        for person in targets
    ]

    assert statuses[-1] == 429
    assert Report.objects.count() == 20
    cache.clear()
