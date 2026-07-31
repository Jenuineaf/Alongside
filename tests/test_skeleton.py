"""Skeleton smoke tests.

⚠️ **WRITTEN BY THE ARCHITECT, OWNED BY QA.**

`tests/` belongs to the QA seat (`testing.md` §3). This one file exists because
CI runs `pytest` with `testpaths = ["tests"]`, and pytest exits non-zero when
that directory is missing or empty — so without it, `main` goes red the moment
the skeleton lands, for a reason that has nothing to do with anyone's code.

It covers items 2 and 3 of QA's own "what I'll do the moment the skeleton lands"
list (`testing.md` §11). QA should absorb it into their structure, extend it, or
delete it once `tests/conftest.py` and the real suites exist — no need to ask.

Everything here is deliberately **database-free**, so it runs before Postgres is
reachable and stays fast. No `@pytest.mark.django_db` anywhere in this file, on
purpose — see `test_healthz_does_not_touch_the_database`.
"""

from django.conf import settings
from django.urls import reverse


def test_healthz_returns_200(client):
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.content == b"ok"


def test_healthz_does_not_touch_the_database(client):
    """The health check must never query Postgres.

    `render.yaml` points its health check at this URL and Render restarts the
    service when it fails, so a health check that queries the database turns a
    brief Neon blip into a restart loop — the outage lasts far longer than the
    blip would have (`deployment.md` §8).

    This test has no `django_db` marker, so pytest-django raises on any database
    access. If someone adds a query to the view, this fails rather than the
    problem being discovered during an incident.
    """
    assert client.get(reverse("healthz")).status_code == 200


def test_auth_user_model_is_the_custom_one():
    """Guards `roadmap.md` ground rule 2 and `data-model.md` §10."""
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_custom_user_lands_in_the_very_first_migration():
    """`User` must be created in `accounts` 0001, alone.

    Swapping `AUTH_USER_MODEL` once other tables reference it is the single most
    painful migration in Django. This asserts the property that keeps that from
    ever being necessary, rather than trusting that nobody reorders the file.
    """
    import importlib

    from django.db.migrations import CreateModel

    # importlib rather than a plain import: the module name starts with a digit.
    migration = importlib.import_module("accounts.migrations.0001_initial").Migration

    assert migration.initial is True

    created = [op.name for op in migration.operations if isinstance(op, CreateModel)]
    assert created == ["User"], (
        f"accounts/0001_initial.py must create User and nothing else, got {created}. "
        "Profile, Follow and Block belong in 0002 — data-model.md §10."
    )


def test_user_renders_a_display_name_without_touching_the_database():
    """`User.name` is what every seat calls to render a user (ADR-0001)."""
    from accounts.models import User

    assert User(username="jeni", display_name="Jeni").name == "Jeni"
    assert User(username="jeni", display_name="").name == "jeni"
