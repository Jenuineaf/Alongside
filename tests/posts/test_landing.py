"""The landing page, and the credentials it publishes.

`product-spec.md` §5.3 prints demo credentials on the login screen — it is the
one screen whose entire job is getting a stranger past the door without signing
up. So the thing worth testing is not that the page renders; it is that **the
credentials it advertises actually work**.

They had already drifted: the view hardcoded a password that `seed_demo` never
set. Nothing failed, no test went red, and the only symptom was a visitor
typing in the published password and being told it was wrong — on the first
screen they ever saw.
"""

import pytest
from django.urls import reverse

from posts.management.commands._seed_corpus import DEMO_ACCOUNTS
from posts.management.commands.seed_demo import SEED_PASSWORD

pytestmark = pytest.mark.django_db


def test_the_published_credentials_actually_log_you_in(client, django_user_model):
    """The whole point of the page. Uses the real constants, not a copy of them."""
    email = DEMO_ACCOUNTS["demo"]["email"]
    user = django_user_model.objects.create_user(
        username=DEMO_ACCOUNTS["demo"]["username"],
        email=email,
        password=SEED_PASSWORD,
        is_demo=True,
        is_public_demo=True,
    )

    assert client.login(email=email, password=SEED_PASSWORD) or client.login(
        username=user.username, password=SEED_PASSWORD
    )


def test_the_landing_page_shows_those_same_credentials(client):
    body = client.get(reverse("posts:landing")).content.decode()

    assert DEMO_ACCOUNTS["demo"]["email"] in body
    assert SEED_PASSWORD in body


def test_the_landing_page_is_public_and_shows_real_posts(client):
    """CLAUDE.md rule 7 — the first impression must not be a login wall."""
    response = client.get(reverse("posts:landing"))

    assert response.status_code == 200
    assert "posts" in response.context
