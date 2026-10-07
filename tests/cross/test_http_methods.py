"""Public pages answer HEAD, not 405.

`require_GET` is `require_http_methods(["GET"])` — it rejects **HEAD**, which
is not an exotic method: crawlers, link checkers, uptime monitors and
link-preview unfurlers all send it before they send anything else, and HTTP
says a resource that answers GET should answer HEAD. Django ships
`require_safe` for exactly this and the two decorators look almost identical,
which is how the wrong one gets used.

It cost nothing visible until something actually sent a HEAD — at which point
the landing page, the one surface the whole product is trying to get strangers
onto, answered **405 Method Not Allowed**.

Parametrised over the public reads rather than spot-checked, because the real
failure mode is somebody adding the sixteenth view with the wrong decorator.
"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PUBLIC_PAGES = [
    "posts:landing",
    "posts:feed",
    "discovery:search",
]


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_public_pages_answer_head(client, name):
    response = client.head(reverse(name))

    assert response.status_code == 200, f"{name} rejected HEAD"


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_public_pages_answer_get(client, name):
    """The other half — `require_safe` must not have broken the normal path."""
    assert client.get(reverse(name)).status_code == 200


def test_head_returns_no_body(client):
    """Django strips it, but assert it: a HEAD that ships a body wastes the
    bandwidth the method exists to save."""
    response = client.head(reverse("posts:landing"))

    assert response.content == b""


def test_write_endpoints_still_refuse_get(client, django_user_model):
    """`require_safe` is for reads only — a state change must stay POST-only,
    or it is reachable from a crawler following a link."""
    user = django_user_model.objects.create_user(
        username="jeni_dev", email="j@example.com", password="pw"
    )
    client.force_login(user)

    assert client.get(reverse("notifications:mark_all_read")).status_code == 405
